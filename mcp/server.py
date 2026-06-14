"""
server.py - local MCP server + live dashboard host (one process, two faces).

  1. MCP tools over stdio  -> Claude Code calls: li_load, li_graph, li_anchors,
     li_topics, li_entities, li_recommend, li_report, li_export
  2. HTTP + SSE on localhost:7700 -> the live cockpit that fills as the analysis runs.

STARTER: works end to end out of the box. The deterministic analysis (graph, orphans,
anchor classes) is complete; the model-driven parts (cluster names, entity extraction,
contextual link anchors) are wired as setter tools the agents call.

Needs the MCP SDK to expose tools to Claude (`pip install mcp`); without it the dashboard
still runs so you can use run.py. Standard library otherwise.
"""
from __future__ import annotations
import json, os, queue, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DASH_DIR = os.path.join(ROOT, "dashboard")
OUT_DIR = os.path.join(ROOT, "outputs")
PORT = int(os.environ.get("LI_PORT", os.environ.get("SEO_PORT", "7700")))
MODEL = os.environ.get("LI_MODEL", os.environ.get("RADAR_MODEL", "gpt-oss:20b-cloud"))

import sys
sys.path.insert(0, ROOT)
from linkintel import analyzer  # noqa: E402

RUN = {"site": None, "urls": 0, "status": "idle",
       "graph_stats": None, "anchors": None, "clusters": None,
       "entities": None, "relatedness": None, "recommendations": None,
       "summary": None}
_A = {}            # full analysis blob (kept out of RUN so /state stays light)
_subs: list[queue.Queue] = []
_lock = threading.Lock()


def _emit(event, data):
    payload = json.dumps({"event": event, "data": data})
    with _lock:
        for q in list(_subs):
            try: q.put_nowait(payload)
            except Exception: pass


def _site(pages):
    if not pages: return "unknown"
    try: return urlparse(pages[0].get("Address", "")).netloc or "unknown"
    except Exception: return "unknown"


# ---------- pipeline tools (importable by run.py without MCP) ----------
def li_load(export_dir: str) -> dict:
    res = analyzer.analyze(export_dir)
    _A.clear(); _A.update(res)
    RUN.update({"urls": res["graph_stats"]["pages_total"],
                "site": _site(res["pages"]), "status": "running",
                "page_text_count": res["page_text_count"]})
    _emit("loaded", {"site": RUN["site"], "urls": RUN["urls"],
                     "page_text": res["page_text_count"]})
    return {"urls": RUN["urls"], "site": RUN["site"], "page_text": res["page_text_count"]}


def li_graph() -> dict:
    g = _A["graph_stats"]
    RUN["graph_stats"] = {
        "pages_total": g["pages_total"], "pages_indexable": g["pages_indexable"],
        "internal_links": g["internal_links"], "max_crawl_depth": g["max_crawl_depth"],
        "avg_inlinks": g["avg_inlinks"],
        "orphan_pages": len(g["orphan_pages"]), "deepest_pages": len(g["deepest_pages"]),
        "under_linked_pages": len(g["under_linked_pages"]),
        "over_linked_pages": len(g["over_linked_pages"]),
        "broken_internal_links": len(g["broken_internal_links"]),
        "broken_links_list": g["broken_internal_links"],
        "redirect_internal_links": len(g["redirect_internal_links"]),
        "nofollow_internal_links": len(g["nofollow_internal_links"]),
    }
    _emit("graph", RUN["graph_stats"])
    return RUN["graph_stats"]


def li_anchors() -> dict:
    a = _A["anchors"]
    RUN["anchors"] = {"generic": len(a["generic_anchors"]),
                      "empty_or_image_only": len(a["empty_or_image_only"]),
                      "over_optimized": len(a["over_optimized_anchors"]),
                      "total": a["total_internal_anchors"],
                      "generic_list": a["generic_anchors"],
                      "over_optimized_list": a["over_optimized_anchors"]}
    _emit("anchors", RUN["anchors"])
    return RUN["anchors"]


def li_topics(names: dict = None) -> dict:
    """Compute clusters; `names` (optional) is {cluster_key: model_chosen_name}."""
    cl = _A["clusters"]["clusters"]
    if names:
        for c in cl:
            if c["key"] in names:
                c["name"] = names[c["key"]]
    RUN["clusters"] = [{"key": c["key"], "name": c["name"], "size": c["size"],
                        "hub_page": c["hub_page"], "authority": c["authority"],
                        "keywords": c["keywords"]} for c in cl]
    _emit("topics", {"clusters": RUN["clusters"]})
    return {"clusters": len(cl)}


def li_entities(entities: dict = None) -> dict:
    """Attach model-extracted entities per page: {url: [entity, ...]}.

    If provided, the relatedness graph is rebuilt on the richer entities.
    """
    if not entities:
        # deterministic TF-IDF fallback if the model hasn't extracted entities
        _A["entities"] = _A.get("clusters", {}).get("page_keywords", {})
    else:
        _A["entities"] = entities
        
    _A["relatedness"] = analyzer.relatedness(_A["entities"], top_per_page=8)
    _A["link_candidates"] = analyzer.link_candidates(
        _A["graph"], _A["relatedness"], _A["pages"], max_per_page=5, clusters_data=_A["clusters"]["clusters"])
        
    RUN["entities"] = {"pages_with_entities": len(_A.get("entities") or {})}
    # Update candidate count so dashboard shows how many are found before enrichment finishes
    RUN["recommendations"] = sum(len(c.get("candidates", [])) for c in _A["link_candidates"])
    _emit("entities", RUN["entities"])
    return RUN["entities"]


def li_set_recommendations(recommendations: list) -> dict:
    """Attach the final contextual link recommendations written by the linker-agent.

    Each item: {source, target, suggested_anchor, relatedness, reason}.
    """
    _A["final_recs"] = recommendations or []
    RUN["recommendations"] = len(_A["final_recs"])
    RUN["recs_list"] = _A["final_recs"]
    _emit("recommendations", {"count": RUN["recommendations"]})
    return {"count": RUN["recommendations"]}


def li_enrich(export_dir: str) -> dict:
    """Run the full model-powered enrichment pipeline (naming, entities, anchors)."""
    from linkintel.analyzer import load_page_text, load_pages
    from linkintel.enrichment import enrich_analysis
    
    page_text = load_page_text(export_dir)
    pages = load_pages(export_dir)
    
    def on_progress(stage, detail):
        _emit("enrichment", {"stage": stage, "detail": detail})
        
    res = enrich_analysis(_A, pages, page_text, progress_callback=on_progress)
    
    if res.get("cluster_names"):
        li_topics(names=res["cluster_names"])
    if res.get("entities"):
        li_entities(entities=res["entities"])
    if res.get("recommendations"):
        li_set_recommendations(res["recommendations"])
        
    calls = res.get("model_calls", 0)
    RUN["model_calls"] = RUN.get("model_calls", 0) + calls
    _emit("enrich_done", {"model_calls": calls})
    return {"model_calls": calls, "enriched": True}


def _report_obj() -> dict:
    g = _A.get("graph_stats", {})
    a = _A.get("anchors", {})
    cl = _A.get("clusters", {}).get("clusters", [])
    recs = _A.get("final_recs")
    if recs is None:
        # starter fallback: surface raw candidates (no anchors) so the contract holds
        recs = []
        for blk in _A.get("link_candidates", []):
            for c in blk["candidates"]:
                recs.append({"source": blk["source"], "target": c["target"],
                             "suggested_anchor": c.get("suggested_anchor"),
                             "relatedness": c["relatedness"],
                             "reason": "shared topics: " + ", ".join(c["shared_topics"])})
    summary = {
        "pages_crawled": g.get("pages_total", 0),
        "indexable_pages": g.get("pages_indexable", 0),
        "internal_links": g.get("internal_links", 0),
        "orphan_pages": len(g.get("orphan_pages", [])),
        "broken_internal_links": len(g.get("broken_internal_links", [])),
        "generic_anchors": len(a.get("generic_anchors", [])),
        "topical_clusters": len(cl),
        "link_recommendations": len(recs),
    }
    RUN["summary"] = summary
    return {
        "site": RUN.get("site", ""),
        "pages_crawled": g.get("pages_total", 0),
        "summary": summary,
        "link_graph": {
            "internal_links": g.get("internal_links", 0),
            "max_crawl_depth": g.get("max_crawl_depth", 0),
            "avg_inlinks": g.get("avg_inlinks", 0),
            "orphan_pages": g.get("orphan_pages", []),
            "deepest_pages": g.get("deepest_pages", []),
            "under_linked_pages": g.get("under_linked_pages", []),
            "over_linked_pages": g.get("over_linked_pages", []),
            "broken_internal_links": g.get("broken_internal_links", []),
            "redirect_internal_links": g.get("redirect_internal_links", []),
            "nofollow_internal_links": g.get("nofollow_internal_links", []),
        },
        "anchor_text": {
            "total_internal_anchors": a.get("total_internal_anchors", 0),
            "generic_anchors": a.get("generic_anchors", []),
            "empty_or_image_only": a.get("empty_or_image_only", []),
            "over_optimized_anchors": a.get("over_optimized_anchors", []),
        },
        "topical_clusters": [
            {"key": c.get("key", ""), "name": c.get("name", ""), "size": c.get("size", 0), "pages": c.get("pages", []),
             "hub_page": c.get("hub_page", ""), "hub_inlinks": c.get("hub_inlinks", 0),
             "authority": c.get("authority", ""), "keywords": c.get("keywords", [])} for c in cl
        ],
        "entity_graph": _A.get("relatedness", {}),
        "link_recommendations": recs,
        "run_meta": {"model": MODEL, "model_calls": RUN.get("model_calls", 0),
                     "duration_sec": RUN.get("duration_sec", 0)},
    }


def li_report() -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "report.json")
    json.dump(_report_obj(), open(p, "w", encoding="utf-8"), indent=2)
    RUN["status"] = "done"; _emit("saved", {"path": p}); return {"path": p}


def li_export() -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "report.html")
    open(p, "w", encoding="utf-8").write(_render_html(_report_obj()))
    _emit("exported", {"path": p}); return {"path": p}


def _render_html(o) -> str:
    s = o["summary"]
    g = o["link_graph"]
    a = o["anchor_text"]
    
    # 1. Executive Summary Metric Sev Status
    def sev(val, t_amber, t_red, lower_is_worse=False):
        if lower_is_worse:
            return "red" if val <= t_red else "amber" if val <= t_amber else "green"
        return "red" if val >= t_red else "amber" if val >= t_amber else "green"
    
    # 2. Graph Tables
    broken_rows = "".join(
        f'<tr><td class="mono">{r["source"].replace("https://","")}</td>'
        f'<td class="mono">{r["destination"].replace("https://","")}</td>'
        f'<td><span class="sev {"high" if int(r["status"])>=500 else "med"}">{r["status"]}</span></td>'
        f'<td>{r["anchor"]}</td></tr>'
        for r in g.get("broken_internal_links", [])[:20]
    ) if isinstance(g.get("broken_internal_links"), list) else '<tr><td colspan=4 class=muted>Raw list not available in state.</td></tr>'

    # 3. Anchor Tables
    generic_rows = "".join(
        f'<tr><td class="mono">{r["source"].replace("https://","")}</td>'
        f'<td class="mono">{r["destination"].replace("https://","")}</td>'
        f'<td><strong>{r["anchor"]}</strong></td></tr>'
        for r in a.get("generic_anchors", [])[:20]
    ) if isinstance(a.get("generic_anchors"), list) else '<tr><td colspan=3 class=muted>Raw list not available in state.</td></tr>'
    
    overopt_rows = "".join(
        f'<tr><td class="mono">{r["destination"].replace("https://","")}</td>'
        f'<td><strong>{r["anchor"]}</strong></td>'
        f'<td>{r["count"]}</td>'
        f'<td>{round(r["share"]*100, 1)}%</td></tr>'
        for r in a.get("over_optimized_anchors", [])[:20]
    ) if isinstance(a.get("over_optimized_anchors"), list) else '<tr><td colspan=4 class=muted>Raw list not available in state.</td></tr>'

    # 4. Clusters
    cl_cards = "".join(
        f'<div class="cluster-card {"gap" if c["authority"]=="scattered" else ""}">'
        f'<h4>{c.get("name") or c["key"]} <span class="sev {"high" if c["authority"]=="hub" else "low"}">{c["authority"]}</span></h4>'
        f'<div class="k"><div style="flex:1"><b>{c["size"]}</b>pages</div>'
        f'<div style="flex:2"><b>Hub</b><span class="mono" style="font-size:11px">{(c["hub_page"] or "none").replace("https://","")}</span></div></div>'
        f'<div style="margin-top:12px;font-size:12px;color:#c8c5be">Top Keywords: {", ".join(c.get("keywords", []))}</div>'
        f'</div>'
        for c in o["topical_clusters"]
    )
    
    # 5. Recommendations (All)
    rec_rows = "".join(
        f'<tr><td class="mono">{r["source"].replace("https://","")}</td>'
        f'<td class="mono">{r["target"].replace("https://","")}</td>'
        f'<td><span class="anchor-badge">{(r.get("suggested_anchor") or "(write anchor)")}</span></td>'
        f'<td>{round(r.get("relatedness", 0), 2) if isinstance(r.get("relatedness"), (int, float)) else r.get("relatedness","")}</td>'
        f'<td class="muted" style="font-size:11px">{r.get("reason","")}</td></tr>'
        for r in o.get("link_recommendations", [])
    )

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Internal Linking Intelligence - {o['site']}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet" />
<style>
:root {{ --bg: #0b0f19; --card: rgba(36, 36, 40, 0.4); --border: rgba(255,255,255,0.1); --text: #f8f7f4; --muted: #aab; --red: #ff4b4b; --amber: #e2b53e; --green: #22c55e; --blue: #6ea8fe; }}
body {{ font-family: 'Inter', system-ui, sans-serif; background: linear-gradient(135deg, #0b0f19, #1c102a); background-attachment: fixed; color: var(--text); margin: 0; padding: 40px; line-height: 1.5; }}
.wrap {{ max-width: 1080px; margin: 0 auto; }}
h1 {{ font-size: 32px; margin: 0 0 8px; font-weight: 700; background: linear-gradient(90deg, #fff, #aab); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
h2 {{ font-size: 20px; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-top: 40px; }}
h3 {{ font-size: 16px; color: var(--blue); margin: 24px 0 12px; }}
.sub {{ color: var(--muted); font-size: 15px; margin-bottom: 30px; }}
.card {{ background: var(--card); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }}
.k {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; }}
.k div {{ font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
.k b {{ display: block; font-size: 32px; color: var(--text); font-weight: 700; margin-bottom: 4px; text-transform: none; letter-spacing: normal; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; margin-bottom: 20px; }}
th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid var(--border); }}
th {{ font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); font-weight: 600; white-space: nowrap; }}
tr:hover td {{ background: rgba(255,255,255,0.02); }}
.mono {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; word-break: break-all; }}
.sev {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 999px; display: inline-block; }}
.sev.high {{ background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }}
.sev.med {{ background: rgba(226, 181, 62, 0.2); color: var(--amber); border: 1px solid rgba(226, 181, 62, 0.3); }}
.sev.low {{ background: rgba(255,255,255,0.1); color: var(--muted); }}
.sev.red {{ color: var(--red); }} .sev.amber {{ color: var(--amber); }} .sev.green {{ color: var(--green); }}
.muted {{ color: var(--muted); font-size: 13px; }}
.cluster-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; margin-top: 16px; }}
.cluster-card {{ background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.cluster-card.gap {{ border-color: rgba(226, 181, 62, 0.4); box-shadow: inset 0 0 20px rgba(226, 181, 62, 0.05); }}
.cluster-card h4 {{ margin: 0 0 12px; font-size: 16px; display: flex; justify-content: space-between; align-items: center; }}
.anchor-badge {{ background: rgba(110, 168, 254, 0.2); color: #93c5fd; padding: 3px 8px; border-radius: 6px; font-weight: 600; }}
.footer {{ margin-top: 60px; text-align: center; font-size: 12px; color: #666; border-top: 1px solid var(--border); padding-top: 20px; }}
@media print {{ body {{ background: #fff; color: #000; padding: 0; }} .card, .cluster-card {{ background: none; border: 1px solid #ccc; box-shadow: none; filter: none; backdrop-filter: none; -webkit-backdrop-filter: none; }} .sev {{ border: 1px solid #999; color: #000 !important; }} h1, h2, h3, th {{ color: #000 !important; -webkit-text-fill-color: #000; }} .anchor-badge {{ background: #eee; color: #000; }} table {{ page-break-inside: auto; }} tr {{ page-break-inside: avoid; page-break-after: auto; }} }}
</style>
</head><body><div class="wrap">

<h1>Internal Linking Intelligence</h1>
<div class="sub">Executive Summary | <strong>{o['site']}</strong> | {o['pages_crawled']} pages crawled</div>

<div class="card k">
  <div><b class="sev {sev(s['internal_links'], 5000, 1000, True)}">{s['internal_links']}</b>Internal Links</div>
  <div><b class="sev {sev(s['orphan_pages'], 5, 20)}">{s['orphan_pages']}</b>Orphan Pages</div>
  <div><b class="sev {sev(s['broken_internal_links'], 10, 50)}">{s['broken_internal_links']}</b>Broken Links</div>
  <div><b class="sev {sev(s['generic_anchors'], 50, 150)}">{s['generic_anchors']}</b>Generic Anchors</div>
  <div><b class="sev green">{s['topical_clusters']}</b>Clusters</div>
  <div><b style="color:var(--blue)">{s['link_recommendations']}</b>Link Suggestions</div>
</div>

<h2>1. Internal Link Graph</h2>
<div class="card">
  <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
    <tr><td>Total Indexable Pages</td><td class="mono">{g['indexable_pages'] if 'indexable_pages' in g else s['pages_crawled']}</td></tr>
    <tr><td>Max Crawl Depth</td><td class="mono">{g['max_crawl_depth']}</td></tr>
    <tr><td>Average Inlinks per Page</td><td class="mono">{g['avg_inlinks']}</td></tr>
    <tr><td>Redirect Internal Links (3xx)</td><td class="mono sev {sev(len(g.get('redirect_internal_links', [])), 10, 50)}">{len(g.get('redirect_internal_links', []))}</td></tr>
    <tr><td>Nofollow Internal Links</td><td class="mono sev {sev(len(g.get('nofollow_internal_links', [])), 1, 10)}">{len(g.get('nofollow_internal_links', []))}</td></tr>
  </tbody></table>
</div>

<div class="card">
  <h3>Top Broken Internal Links (4xx/5xx)</h3>
  <table><thead><tr><th>Source</th><th>Destination</th><th>Status</th><th>Anchor</th></tr></thead>
  <tbody>{broken_rows or '<tr><td colspan=4 class=muted>No broken links found.</td></tr>'}</tbody></table>
</div>

<h2>2. Anchor Text Audit</h2>
<div class="card">
  <h3>Top Generic Anchors</h3>
  <table><thead><tr><th>Source</th><th>Destination</th><th>Anchor Text</th></tr></thead>
  <tbody>{generic_rows or '<tr><td colspan=3 class=muted>No generic anchors found.</td></tr>'}</tbody></table>
</div>

<div class="card">
  <h3>Over-Optimized Anchors (Exact Match)</h3>
  <table><thead><tr><th>Target Destination</th><th>Exact Match Anchor</th><th>Count</th><th>Share %</th></tr></thead>
  <tbody>{overopt_rows or '<tr><td colspan=4 class=muted>No over-optimized anchors detected.</td></tr>'}</tbody></table>
</div>

<h2>3. Topical Clusters & Authority</h2>
<div class="cluster-grid">
  {cl_cards or '<div class="muted">No clusters generated.</div>'}
</div>

<h2>4. Contextual Link Recommendations</h2>
<div class="card" style="padding: 0; overflow-x: auto;">
  <table style="margin:0;"><thead><tr><th>Source Page</th><th>Should Link To</th><th>Suggested Anchor</th><th>Rel.</th><th>Reason</th></tr></thead>
  <tbody>{rec_rows or '<tr><td colspan=5 class=muted style="padding:20px;">No recommendations generated.</td></tr>'}</tbody></table>
</div>

<div class="footer">
  Generated by Link Intel Suite • Model: {o.get('run_meta', dict()).get('model', 'unknown')} • Duration: {o.get('run_meta', dict()).get('duration_sec', 0)}s
</div>
</div></body></html>"""



# ---------- dashboard HTTP host ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache"); self.end_headers()
        self.wfile.write(body.encode() if isinstance(body, str) else body)
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            p = os.path.join(DASH_DIR, "index.html")
            self._send(200, open(p, encoding="utf-8").read() if os.path.exists(p) else "no dashboard")
        elif self.path == "/app.js":
            p = os.path.join(DASH_DIR, "app.js")
            self._send(200, open(p, encoding="utf-8").read() if os.path.exists(p) else "", "application/javascript")
        elif self.path == "/state":
            self._send(200, json.dumps(RUN), "application/json")
        elif self.path == "/events":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            q = queue.Queue()
            with _lock: _subs.append(q)
            try:
                self.wfile.write(f"data: {json.dumps({'event':'snapshot','data':RUN})}\n\n".encode()); self.wfile.flush()
                while True:
                    try: self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                    except queue.Empty: self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception: pass
            finally:
                with _lock:
                    if q in _subs: _subs.remove(q)
        else: self._send(404, "not found")


def start_dashboard(port=PORT):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _run_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print(f"[li] MCP SDK not found. Dashboard only at http://localhost:{PORT}", flush=True)
        while True: time.sleep(3600)
    mcp = FastMCP("link-intel-suite")

    @mcp.tool()
    def load(export_dir: str) -> dict:
        """Load a Screaming Frog export (internal_html.csv + all_inlinks.csv + page text/)."""
        return li_load(export_dir)

    @mcp.tool()
    def graph_stats() -> dict:
        """Run the deterministic internal-link graph analysis (orphans, depth, broken/redirect/nofollow)."""
        return li_graph()

    @mcp.tool()
    def anchors() -> dict:
        """Run anchor-text analysis (generic, empty/image-only, over-optimized)."""
        return li_anchors()

    @mcp.tool()
    def topics(names: dict = None) -> dict:
        """Compute topical clusters; optionally attach model-chosen cluster names {key:name}."""
        return li_topics(names)

    @mcp.tool()
    def entities(entities: dict = None) -> dict:
        """Attach model-extracted entities per page {url:[entity,...]} and rebuild the entity graph."""
        return li_entities(entities)

    @mcp.tool()
    def recommend(recommendations: list) -> dict:
        """Attach the final contextual link recommendations [{source,target,suggested_anchor,relatedness,reason}]."""
        return li_set_recommendations(recommendations)

    @mcp.tool()
    def enrich(export_dir: str) -> dict:
        """Run the full model-powered enrichment pipeline."""
        return li_enrich(export_dir)

    @mcp.tool()
    def write_report() -> dict:
        """Write outputs/report.json (the grader reads this)."""
        return li_report()

    @mcp.tool()
    def export_report() -> dict:
        """Write outputs/report.html (the client deliverable)."""
        return li_export()

    mcp.run()


if __name__ == "__main__":
    start_dashboard()
    print(f"[li] dashboard live at http://localhost:{PORT}", flush=True)
    _run_mcp()
