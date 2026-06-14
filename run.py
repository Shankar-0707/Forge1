#!/usr/bin/env python3
"""
run.py - headless runner for the Link Intel Suite (also the grader's entry point).

Runs the full internal-linking analysis on a Screaming Frog export with no Claude Code:
  load -> graph -> anchors -> topics -> entities (TF proxy) -> recommend (candidates)
       -> write report.json + report.html

Usage:
  python run.py sample-export/
  python run.py sample-export/ --no-dashboard

The model-driven steps (cluster naming, entity extraction, writing the contextual link
anchors) are left as build TODOs; the starter writes deterministic placeholders so the
report.json contract stays valid and the pipeline always produces a graded artifact.
"""
from __future__ import annotations
import argparse, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "mcp"))
sys.path.insert(0, HERE)
# pyrefly: ignore [missing-import]
import server  # the MCP server module exposes every tool as a function


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--no-dashboard", action="store_true")
    args = ap.parse_args()

    if not args.no_dashboard:
        server.start_dashboard()
        print(f"[li] dashboard: http://localhost:{server.PORT}", flush=True)
        time.sleep(1)

    t0 = time.time()
    server.li_load(args.export_dir)
    server.li_graph()
    server.li_anchors()
    server.li_topics()        # no model names in headless mode (cluster keys used)
    server.li_entities()      # uses TF-keyword relatedness proxy
    
    # --- ENRICHMENT PIPELINE ---
    from linkintel.analyzer import load_page_text, load_pages
    from linkintel.enrichment import enrich_analysis
    from linkintel.model_client import model_available, model_call_count, model_name
    
    page_text = load_page_text(args.export_dir)
    pages = load_pages(args.export_dir)
    
    available = model_available()
    print(f"\n[li] Model {model_name()} available: {available}", flush=True)
    
    def on_progress(stage, detail):
        print(f"  [enrichment] {stage}: {detail}", flush=True)
        
    enrich_results = enrich_analysis(server._A, pages, page_text, progress_callback=on_progress)
    
    if enrich_results.get("cluster_names"):
        server.li_topics(names=enrich_results["cluster_names"])
    if enrich_results.get("entities"):
        server.li_entities(entities=enrich_results["entities"])
    if enrich_results.get("recommendations"):
        server.li_set_recommendations(enrich_results["recommendations"])

    server.RUN["model_calls"] = model_call_count()
    server.RUN["duration_sec"] = round(time.time() - t0, 1)
    server.li_report()
    server.li_export()

    s = server.RUN["summary"]
    print("\n=== INTERNAL LINKING INTELLIGENCE ===")
    print(f"Site            : {server.RUN['site']}  ({s['pages_crawled']} pages)")
    print(f"Internal links  : {s['internal_links']}")
    print(f"Orphan pages    : {s['orphan_pages']}")
    print(f"Broken internal : {s['broken_internal_links']}")
    print(f"Generic anchors : {s['generic_anchors']}")
    print(f"Topical clusters: {s['topical_clusters']}")
    print(f"Link suggestions: {s['link_recommendations']}")
    print("Wrote outputs/report.json and outputs/report.html")


if __name__ == "__main__":
    main()
