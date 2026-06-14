"""
analyzer.py - deterministic internal-linking + topical-authority analysis from a
Screaming Frog export (internal_html.csv + all_inlinks.csv + all_outlinks.csv +
all_anchor_text.csv + a page text/ folder).

STARTER IMPLEMENTATION. It already builds the internal link graph, detects orphan
pages, deepest pages, broken/redirect/nofollow internal links and basic anchor-text
problems so the pipeline runs end to end. Your job in the build is to COMPLETE the
analysis (see rulebook.md): finish the anchor classes, build the topical clusters,
the entity graph, and feed the linker. The grader uses these same definitions.

Standard library only (csv). The heavy lifting (graph, orphans, anchor classes) is
deterministic Python on purpose - the model is for entity extraction, cluster naming
and writing the contextual link suggestions, NOT for counting rows.
"""
from __future__ import annotations
import csv, os, re, math
from collections import defaultdict, Counter
from urllib.parse import urlparse

from linkintel.tfidf import tfidf_vectors, cosine_similarity, cluster_by_similarity, extract_bigrams, tokenize

csv.field_size_limit(10_000_000)

# --------------------------------------------------------------------------- #
# generic / non-descriptive anchors (lowercased, stripped). Extend per rulebook.
# --------------------------------------------------------------------------- #
GENERIC_ANCHORS = {
    "click here", "read more", "read more...", "learn more", "more", "here",
    "this", "this page", "link", "view more", "see more", "details", "more details",
    "know more", "discover more", "find out more", "continue reading", "go",
    "click", "view", "see details", "more info", "info",
    "visit", "visit us", "check it out", "see all", "browse", "explore", "start",
    "get started", "submit", "go here", "follow", "follow this", "full article",
    "source", "reference", "website", "homepage", "page", "post"
}

STOPWORDS = set("""a an the and or but if then else for to of in on at by with from as is are was were be been being this that these those it its we you they he she them our your their i me my mine our ours us not no yes do does did doing have has had having will would can could should may might must shall about into over under again further once here there all any both each few more most other some such only own same so than too very s t can just don now get got also into out up down off above below""".split())


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _int(v, d=0):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return d


def _norm(u: str) -> str:
    """Normalise a URL for matching (drop trailing slash, fragment)."""
    if not u:
        return ""
    u = u.split("#")[0].strip()
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u


def is_html(r):  return "text/html" in (r.get("Content Type", "") or "").lower()
def is_200(r):   return _int(r.get("Status Code")) == 200
def indexable(r): return (r.get("Indexability", "") or "").strip().lower() == "indexable"


def load_pages(export_dir: str) -> list[dict]:
    """Load internal_html.csv (falls back to internal_all.csv)."""
    for name in ("internal_html.csv", "internal_all.csv"):
        p = os.path.join(export_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
    raise FileNotFoundError("internal_html.csv / internal_all.csv not found in export dir")


def load_links(export_dir: str, fname="all_inlinks.csv") -> list[dict]:
    p = os.path.join(export_dir, fname)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_page_text(export_dir: str) -> dict:
    """Map normalised URL -> body text from the page text/ folder.

    Filenames are URL-encoded, e.g.
      original_https_nmgtechnologies.com_advanced-seo-case-studies.txt
    We reconstruct the URL by stripping the prefix and decoding.
    """
    out = {}
    folder = None
    for cand in ("page text", "page_text", "pagetext"):
        d = os.path.join(export_dir, cand)
        if os.path.isdir(d):
            folder = d
            break
    if not folder:
        return out
    from urllib.parse import unquote
    for fn in os.listdir(folder):
        if not fn.endswith(".txt"):
            continue
        stem = fn[:-4]
        stem = re.sub(r"^original_", "", stem)
        # original_https_host_path -> https://host/path
        stem = stem.replace("https_", "https://", 1).replace("http_", "http://", 1)
        # remaining underscores in the path segment were '/'
        if "://" in stem:
            scheme, rest = stem.split("://", 1)
            rest = rest.replace("_", "/")
            url = f"{scheme}://{rest}"
        else:
            url = stem.replace("_", "/")
        url = unquote(url)
        try:
            with open(os.path.join(folder, fn), encoding="utf-8", errors="ignore") as f:
                out[_norm(url)] = f.read()
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# 1. INTERNAL LINK GRAPH  (deterministic - DONE in starter)
# --------------------------------------------------------------------------- #
def build_graph(pages, inlinks):
    """Return graph structures from the crawl.

    Uses only internal Hyperlink rows whose Source AND Destination are crawled
    pages. Returns adjacency (out), reverse adjacency (in), and per-page degree.
    """
    page_set = {_norm(p["Address"]) for p in pages}
    out_adj = defaultdict(set)
    in_adj = defaultdict(set)
    follow_in = defaultdict(int)
    for r in inlinks:
        if r.get("Type") != "Hyperlink":
            continue
        s = _norm(r.get("Source", ""))
        d = _norm(r.get("Destination", ""))
        if not s or not d or s == d:
            continue
        if d not in page_set:
            continue  # only count links pointing at crawled internal pages
        out_adj[s].add(d)
        in_adj[d].add(s)
        if (r.get("Follow", "true") or "true").strip().lower() == "true":
            follow_in[d] += 1
    return {"page_set": page_set, "out": out_adj, "in": in_adj, "follow_in": follow_in}


def graph_stats(pages, inlinks, graph) -> dict:
    """Internal-link graph statistics + structural issues.

    Definitions (match the rulebook):
      orphan_page          : indexable 200 html page with Unique Inlinks == 0
      deepest_pages        : indexable pages at the maximum Crawl Depth (>=3 listed)
      under_linked         : indexable 200 page with Unique Inlinks <= UNDER (default 1)
      over_linked          : page in the top 5% by Unique Inlinks (sitewide nav noise)
      broken_internal_link : all_inlinks rows with Status Code 400-599
      redirect_internal    : all_inlinks rows with Status Code 300-399 (3xx)
      nofollow_internal    : all_inlinks Hyperlink rows with Follow == false
    """
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    by_url = {_norm(p["Address"]): p for p in pages}

    # orphans (use SF's own Unique Inlinks column - authoritative)
    orphans = sorted(_norm(p["Address"]) for p in idx200 if _int(p.get("Unique Inlinks")) == 0)

    # deepest
    depth = {_norm(p["Address"]): _int(p.get("Crawl Depth")) for p in idx200}
    maxd = max(depth.values()) if depth else 0
    deepest = sorted([u for u, d in depth.items() if d == maxd])

    # under/over linked by Unique Inlinks
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    UNDER = 1
    under_linked = sorted([u for u, n in inl.items() if n <= UNDER])
    vals = sorted(inl.values())
    over_thresh = vals[int(len(vals) * 0.95)] if vals else 0
    over_linked = sorted([u for u, n in inl.items() if n >= max(over_thresh, 1) and n == max(vals or [0])][:0]) \
        or sorted([u for u, n in inl.items() if over_thresh and n >= over_thresh])

    # broken / redirect / nofollow internal links (from all_inlinks)
    broken, redir, nofollow = [], [], []
    for r in inlinks:
        sc = _int(r.get("Status Code"))
        typ = r.get("Type", "")
        dst = _norm(r.get("Destination", ""))
        src = _norm(r.get("Source", ""))
        if typ == "Hyperlink" and 400 <= sc <= 599:
            broken.append({"source": src, "destination": dst, "status": sc,
                           "anchor": (r.get("Anchor", "") or "").strip()})
        if typ == "Hyperlink" and 300 <= sc <= 399:
            redir.append({"source": src, "destination": dst, "status": sc,
                          "anchor": (r.get("Anchor", "") or "").strip()})
        if typ == "Hyperlink" and (r.get("Follow", "true") or "").strip().lower() == "false":
            nofollow.append({"source": src, "destination": dst,
                             "anchor": (r.get("Anchor", "") or "").strip()})

    return {
        "pages_total": len(pages),
        "pages_indexable": len(idx200),
        "internal_links": sum(len(v) for v in graph["out"].values()),
        "max_crawl_depth": maxd,
        "orphan_pages": orphans,
        "deepest_pages": deepest,
        "under_linked_pages": under_linked,
        "over_linked_pages": over_linked,
        "broken_internal_links": broken,
        "redirect_internal_links": redir,
        "nofollow_internal_links": nofollow,
        "avg_inlinks": round(sum(inl.values()) / len(inl), 1) if inl else 0,
    }


# --------------------------------------------------------------------------- #
# 2. ANCHOR TEXT ANALYSIS  (starter: generic + empty done; TODO: exact-match)
# --------------------------------------------------------------------------- #
def anchor_analysis(inlinks) -> dict:
    """Classify internal Hyperlink anchors.

    generic_anchors      : anchor (lowercased) in GENERIC_ANCHORS
    empty_or_image_only  : Hyperlink row with empty Anchor (image link / bare link)
    over_optimized       : TODO - the SAME exact-match keyword anchor used to point at
                           one destination from many sources (keyword stuffing signal)
    """
    hyper = [r for r in inlinks if r.get("Type") == "Hyperlink"]
    generic, empty = [], []
    dest_anchor = defaultdict(Counter)  # destination -> Counter(anchor)
    for r in hyper:
        a = (r.get("Anchor", "") or "").strip()
        al = a.lower()
        src = _norm(r.get("Source", ""))
        dst = _norm(r.get("Destination", ""))
        if not a:
            empty.append({"source": src, "destination": dst})
            continue
        if al in GENERIC_ANCHORS:
            generic.append({"source": src, "destination": dst, "anchor": a})
        dest_anchor[dst][al] += 1

    # TODO (build): over-optimized exact-match. Starter flags destinations where a
    # single non-generic anchor accounts for a large share AND a high count.
    over = []
    for dst, ctr in dest_anchor.items():
        total = sum(ctr.values())
        if total < 10:
            continue
        anchor, cnt = ctr.most_common(1)[0]
        if anchor and anchor not in GENERIC_ANCHORS and cnt / total >= 0.6 and cnt >= 10:
            over.append({"destination": dst, "anchor": anchor, "count": cnt, "share": round(cnt / total, 2)})

    return {
        "generic_anchors": generic,
        "empty_or_image_only": empty,
        "over_optimized_anchors": sorted(over, key=lambda x: -x["count"]),
        "total_internal_anchors": len(hyper),
    }


# --------------------------------------------------------------------------- #
# 3. TOPICAL CLUSTERS  (starter: path-prefix + keyword TF; TODO: refine + name)
# --------------------------------------------------------------------------- #
def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower())
            if w not in STOPWORDS]


def page_keywords(page, body: str, top=15, global_df=None, total_pages=0) -> list[str]:
    """TF keywords from Title + H1 + H2 + body (weighted), plus bigrams."""
    c = Counter()
    
    parts = [
        (page.get("Title 1", "") or "", 3),
        (page.get("H1-1", "") or "", 2),
        ((page.get("H2-1", "") or "") + " " + (page.get("H2-2", "") or ""), 1.5),
        ((body or "")[:6000], 1)
    ]
    
    for text, weight in parts:
        if not text.strip(): continue
        toks = tokenize(text)
        bigrams = extract_bigrams(toks, top_n=20)
        for t in toks + bigrams:
            c[t] += weight
            
    if global_df and total_pages > 0:
        threshold = 0.4 * total_pages
        for t in list(c.keys()):
            if global_df.get(t, 0) > threshold:
                c[t] *= 0.1
                
    single_kws = Counter({k: v for k, v in c.items() if " " not in k})
    bigram_kws = Counter({k: v for k, v in c.items() if " " in k})
    
    n_single = int(top * 0.6)
    n_bigram = top - n_single
    
    res = [w for w, _ in single_kws.most_common(n_single)]
    res += [w for w, _ in bigram_kws.most_common(n_bigram)]
    
    if len(res) < top:
        remaining = top - len(res)
        all_other = [w for w, _ in c.most_common() if w not in res]
        res += all_other[:remaining]
        
    return res


def cluster_pages(pages, page_text, n_keywords=15) -> dict:
    """Group indexable pages into topical clusters using TF-IDF similarity."""
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    
    global_df = Counter()
    for p in idx200:
        u = _norm(p["Address"])
        body = page_text.get(u, "")
        t1 = p.get("Title 1", "") or ""
        h1 = p.get("H1-1", "") or ""
        h2 = (p.get("H2-1", "") or "") + " " + (p.get("H2-2", "") or "")
        b = (body or "")[:6000]
        toks = set(tokenize(t1 + " " + h1 + " " + h2 + " " + b))
        global_df.update(toks)
        
    total_pages = len(idx200)
    
    kw = {}
    combined_text = {}
    
    for p in idx200:
        u = _norm(p["Address"])
        body = page_text.get(u, "")
        kw[u] = page_keywords(p, body, n_keywords, global_df=global_df, total_pages=total_pages)
        
        t1 = p.get("Title 1", "") or ""
        h1 = p.get("H1-1", "") or ""
        h2 = (p.get("H2-1", "") or "") + " " + (p.get("H2-2", "") or "")
        b = (body or "")[:6000]
        combined_text[u] = f"{t1} {h1} {h2} {b}"

    vectors, _ = tfidf_vectors(combined_text)
    sim_clusters = cluster_by_similarity(vectors, threshold=0.12)
    
    clustered_urls = {u for cluster in sim_clusters for u in cluster}
    
    fallback_clusters = defaultdict(list)
    for p in idx200:
        u = _norm(p["Address"])
        if u not in clustered_urls:
            path = urlparse(u).path.strip("/")
            seg = path.split("/")[0] if path else "(home)"
            fallback_clusters[seg].append(u)
            
    all_clusters_raw = sim_clusters + list(fallback_clusters.values())
    
    out = []
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    
    for members in all_clusters_raw:
        if not members:
            continue
        members = sorted(members)
        hub = max(members, key=lambda u: inl.get(u, 0)) if members else None
        hub_inlinks = inl.get(hub, 0)
        member_inl = sorted((inl.get(m, 0) for m in members), reverse=True)
        clear_hub = bool(len(member_inl) >= 2 and hub_inlinks >= 2 * (member_inl[1] or 1))
        
        ck = Counter()
        for m in members:
            for word in kw.get(m, []):
                ck[word] += 1
                
        top_kws = [w for w, _ in ck.most_common(3)]
        name = " & ".join(top_kws) if top_kws else "misc"
        key = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if not key:
            key = "misc"
            
        out.append({
            "key": key,
            "name": name,
            "size": len(members),
            "pages": members,
            "hub_page": hub,
            "hub_inlinks": hub_inlinks,
            "authority": "hub" if clear_hub else "scattered",
            "keywords": [w for w, _ in ck.most_common(8)],
        })
        
    out.sort(key=lambda x: -x["size"])
    return {"clusters": out, "page_keywords": kw}


# --------------------------------------------------------------------------- #
# 4. ENTITY GRAPH  (starter: TF-overlap relatedness; TODO: model entities)
# --------------------------------------------------------------------------- #
def relatedness(page_keywords: dict, top_per_page=8) -> dict:
    """Page-to-page topical relatedness via weighted keyword Jaccard overlap."""
    urls = list(page_keywords.keys())
    sets = {u: set(page_keywords[u]) for u in urls}
    
    df = Counter()
    for s in sets.values():
        df.update(s)
    N = len(urls)
    idf = {term: math.log(N / (count + 1)) for term, count in df.items()}
    
    edges = {}
    for u in urls:
        scored = []
        su = sets[u]
        if not su:
            edges[u] = []
            continue
            
        weight_su = sum(idf.get(t, 0) for t in su)
        
        for v in urls:
            if v == u:
                continue
            sv = sets[v]
            if not sv:
                continue
                
            inter = su & sv
            if not inter:
                continue
                
            weight_inter = sum(idf.get(t, 0) for t in inter)
            weight_sv = sum(idf.get(t, 0) for t in sv)
            
            union_weight = weight_su + weight_sv - weight_inter
            if union_weight <= 0: continue
            
            jac = weight_inter / union_weight
            if jac >= 0.05:
                scored.append((v, round(jac, 3), sorted(inter)[:6]))
                
        scored.sort(key=lambda x: -x[1])
        edges[u] = [{"to": v, "score": s, "shared": sh} for v, s, sh in scored[:top_per_page]]
        
    return edges


# --------------------------------------------------------------------------- #
# 5. CONTEXTUAL LINK RECOMMENDATIONS  (starter: candidates; model writes anchors)
# --------------------------------------------------------------------------- #
def link_candidates(graph, relate: dict, pages, max_per_page=5, clusters_data=None) -> list:
    """For each important page, find topically-related pages it does NOT already link to."""
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    
    UNDER = 1
    under_linked_set = {u for u, count in inl.items() if count <= UNDER}
    
    scattered_set = set()
    if clusters_data:
        for c in clusters_data:
            if c.get("authority") == "scattered":
                scattered_set.update(c.get("pages", []))
                
    titles = {}
    for p in idx200:
        u = _norm(p["Address"])
        titles[u] = p.get("Title 1", "") or ""
        
    important = sorted(inl.keys(), key=lambda u: -inl[u])[:60]
    out = []
    
    for u in important:
        already = graph["out"].get(u, set())
        cands = []
        for e in relate.get(u, []):
            v = e["to"]
            if v in already or v == u:
                continue
                
            base_score = e["score"]
            mult = 1.0
            reasons = [f"shared topics: {', '.join(e['shared'][:2])}"]
            
            if v in under_linked_set:
                mult *= 2.0
                reasons.append("fixes under-linked page")
            if v in scattered_set:
                mult *= 1.5
                reasons.append("supports scattered cluster")
                
            final_score = base_score * mult
            
            raw_title = titles.get(v, "")
            clean_title = re.split(r'\s+[|\-]\s+', raw_title)[0].strip().lower()
            words = clean_title.split()
            anchor = " ".join(words[:6])
            
            cands.append({
                "target": v, 
                "relatedness": base_score, 
                "shared_topics": e["shared"],
                "composite_score": round(final_score, 3),
                "suggested_anchor": anchor if anchor else "read more",
                "reason": "; ".join(reasons)
            })
            
        cands.sort(key=lambda x: -x["composite_score"])
        cands = cands[:max_per_page]
        
        if cands:
            out.append({"source": u, "candidates": cands})
            
    return out


# --------------------------------------------------------------------------- #
# orchestration entry used by server.py / run.py
# --------------------------------------------------------------------------- #
def analyze(export_dir: str) -> dict:
    pages = load_pages(export_dir)
    inlinks = load_links(export_dir, "all_inlinks.csv")
    text = load_page_text(export_dir)
    graph = build_graph(pages, inlinks)
    gstats = graph_stats(pages, inlinks, graph)
    anchors = anchor_analysis(inlinks)
    clusters = cluster_pages(pages, text)
    relate = relatedness(clusters["page_keywords"])
    cands = link_candidates(graph, relate, pages, clusters_data=clusters["clusters"])
    return {
        "pages": pages, "graph": graph, "graph_stats": gstats,
        "anchors": anchors, "clusters": clusters, "relatedness": relate,
        "link_candidates": cands, "page_text_count": len(text),
    }


if __name__ == "__main__":
    import sys, json
    d = sys.argv[1] if len(sys.argv) > 1 else "../sample-export"
    res = analyze(d)
    g = res["graph_stats"]
    print(f"pages={g['pages_total']} indexable={g['pages_indexable']} "
          f"links={g['internal_links']} maxdepth={g['max_crawl_depth']}")
    print(f"orphans={len(g['orphan_pages'])} under_linked={len(g['under_linked_pages'])} "
          f"over_linked={len(g['over_linked_pages'])}")
    print(f"broken_internal={len(g['broken_internal_links'])} "
          f"redirect_internal={len(g['redirect_internal_links'])} "
          f"nofollow_internal={len(g['nofollow_internal_links'])}")
    a = res["anchors"]
    print(f"generic_anchors={len(a['generic_anchors'])} empty={len(a['empty_or_image_only'])} "
          f"over_optimized={len(a['over_optimized_anchors'])}")
    print(f"clusters={len(res['clusters']['clusters'])} "
          f"link_candidate_pages={len(res['link_candidates'])} "
          f"page_text={res['page_text_count']}")
