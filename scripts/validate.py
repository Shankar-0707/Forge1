import json
import os
import sys

def check(name, condition, details=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition and details:
        print(f"       -> {details}")
    return condition

def main():
    report_path = os.path.join(os.path.dirname(__file__), "..", "outputs", "report.json")
    if not os.path.exists(report_path):
        print(f"FAIL: {report_path} not found")
        sys.exit(1)
        
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"FAIL: Could not parse JSON: {e}")
        sys.exit(1)
        
    all_passed = True
    
    # 1. Top-level keys
    req_keys = ["site", "pages_crawled", "summary", "link_graph", "anchor_text", 
                "topical_clusters", "entity_graph", "link_recommendations", "run_meta"]
    for k in req_keys:
        all_passed &= check(f"Top-level key '{k}' exists", k in data, f"Missing key: {k}")
        
    if not all_passed:
        print("\nFix top-level keys before continuing.")
        sys.exit(1)
        
    # 2. Summary fields
    summary = data["summary"]
    sum_keys = ["pages_crawled", "indexable_pages", "internal_links", "orphan_pages", 
                "broken_internal_links", "generic_anchors", "topical_clusters", "link_recommendations"]
    for k in sum_keys:
        all_passed &= check(f"Summary key '{k}' exists", k in summary, f"Missing in summary: {k}")

    # 3. Recommendations
    recs = data["link_recommendations"]
    all_passed &= check("Recommendations is list", isinstance(recs, list))
    for i, r in enumerate(recs):
        valid = all(k in r for k in ["source", "target", "suggested_anchor"])
        all_passed &= check(f"Recommendation {i} schema", valid, f"Missing keys in {r}")
        if not valid: break
        
    # 4. Broken Links
    broken = data["link_graph"]["broken_internal_links"]
    all_passed &= check("Broken links is list", isinstance(broken, list))
    for i, r in enumerate(broken):
        valid = all(k in r for k in ["source", "destination", "status"])
        all_passed &= check(f"Broken link {i} schema", valid, f"Missing keys in {r}")
        if not valid: break
        
    # 5. Over-optimized anchors
    over = data["anchor_text"]["over_optimized_anchors"]
    all_passed &= check("Over-optimized is list", isinstance(over, list))
    for i, r in enumerate(over):
        valid = all(k in r for k in ["destination", "anchor", "count"])
        all_passed &= check(f"Over-optimized anchor {i} schema", valid, f"Missing keys in {r}")
        if not valid: break
        
    # 6. Topical Clusters
    clusters = data["topical_clusters"]
    all_passed &= check("Clusters is list", isinstance(clusters, list))
    for i, c in enumerate(clusters):
        valid = all(k in c for k in ["key", "size", "pages", "authority"])
        all_passed &= check(f"Cluster {i} schema", valid, f"Missing keys in {c}")
        if not valid: break
        
        auth_valid = c["authority"] in ("hub", "scattered")
        all_passed &= check(f"Cluster {i} authority is hub/scattered", auth_valid, f"Invalid authority: {c['authority']}")
        if not auth_valid: break
        
    # 7. Entity Graph
    egraph = data["entity_graph"]
    all_passed &= check("Entity graph is dict", isinstance(egraph, dict))
    for url, edges in egraph.items():
        if not edges: continue
        valid = all(k in edges[0] for k in ["to", "score"])
        all_passed &= check(f"Entity graph edge schema", valid, f"Missing keys in {edges[0]}")
        break

    # 8. Run meta
    meta = data["run_meta"]
    all_passed &= check("Run meta has model_calls", "model_calls" in meta)
    
    print("\n===========================")
    if all_passed:
        print("ALL VALIDATION CHECKS PASSED!")
    else:
        print("SOME CHECKS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    main()
