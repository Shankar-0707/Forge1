import sys
sys.path.insert(0, '.')
from linkintel.analyzer import load_pages, load_links, load_page_text, cluster_pages, page_keywords
from linkintel.tfidf import tfidf_vectors, cluster_by_similarity
from collections import defaultdict
import re

print("Loading...")
export_dir = "../sample-export"
pages = load_pages(export_dir)
page_text = load_page_text(export_dir)

print("Starting custom debug...")
def _norm(u):
    u = u.split("#")[0].strip()
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u

def is_html(r):  return "text/html" in (r.get("Content Type", "") or "").lower()
def is_200(r):
    try:
        return int(float(str(r.get("Status Code")).strip())) == 200
    except Exception:
        return False
def indexable(r): return (r.get("Indexability", "") or "").strip().lower() == "indexable"

idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
kw = {}
combined_text = {}
print("Building page keywords...")
for p in idx200:
    u = _norm(p["Address"])
    body = page_text.get(u, "")
    kw[u] = page_keywords(p, body, 15)
    
    t1 = p.get("Title 1", "") or ""
    h1 = p.get("H1-1", "") or ""
    h2 = (p.get("H2-1", "") or "") + " " + (p.get("H2-2", "") or "")
    b = (body or "")[:6000]
    combined_text[u] = f"{t1} {h1} {h2} {b}"

print("Building TFIDF vectors...")
vectors, _ = tfidf_vectors(combined_text)

print("Running cluster_by_similarity...")
sim_clusters = cluster_by_similarity(vectors, threshold=0.12)

print("Finished cluster_by_similarity!")
