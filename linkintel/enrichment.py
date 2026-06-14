import json
from typing import List, Dict, Any
from linkintel.model_client import model_available, model_generate, get_client

def name_clusters(clusters: List[Dict], page_keywords: Dict) -> Dict[str, str]:
    """Return {cluster_key: "Human Readable Name"} for each cluster."""
    cluster_names = {}
    
    if model_available():
        batch_size = 8
        for i in range(0, len(clusters), batch_size):
            batch = clusters[i:i+batch_size]
            cluster_details = ""
            for c in batch:
                kws = c.get("keywords", {})
                kw_list = list(kws.keys()) if isinstance(kws, dict) else list(kws)
                cluster_details += f"Cluster Key: {c['key']}\nKeywords: {kw_list}\n\n"
            
            prompt = (
                "Given these topic clusters with their keywords, give each a short descriptive name (2-5 words).\n"
                "Return JSON: {\"key1\": \"Name 1\", ...}\n\nClusters:\n" + cluster_details
            )
            
            try:
                response = model_generate(prompt)
                parsed = get_client().extract_json(response)
                if isinstance(parsed, dict):
                    cluster_names.update(parsed)
            except Exception as e:
                print(f"[Warning] Failed to name cluster batch: {e}")
                
    # Fallback for missing
    for c in clusters:
        key = c["key"]
        if key not in cluster_names:
            kws = c.get("keywords", {})
            if isinstance(kws, dict):
                top_kws = list(kws.keys())[:3]
            else:
                top_kws = list(kws)[:3]
            cluster_names[key] = " & ".join([kw.title() for kw in top_kws])
            
    return cluster_names

def extract_entities_batch(pages: List[Dict], page_text: Dict, page_keywords: Dict, batch_size: int = 5) -> Dict[str, List[str]]:
    """Return {url: [entity1, entity2, ...]} for each page."""
    entities = {}
    
    if model_available():
        for i in range(0, len(pages), batch_size):
            batch = pages[i:i+batch_size]
            page_details = ""
            for p in batch:
                url = p["url"]
                text = page_text.get(url, "")[:500]
                page_details += f"URL: {url}\nTitle: {p.get('title', '')}\nText: {text}\n\n"
                
            prompt = (
                "For each page below, extract 5-8 key entities (services, technologies, concepts).\n"
                "Return JSON: {\"url1\": [\"entity1\", ...], ...}\n\nPages:\n" + page_details
            )
            
            try:
                response = model_generate(prompt)
                parsed = get_client().extract_json(response)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            entities[k] = v
            except Exception as e:
                print(f"[Warning] Failed to extract entities batch: {e}")
                
    # Fallback for missing
    for p in pages:
        url = p["url"]
        if url not in entities:
            # deterministic fallback
            kws = page_keywords.get(url, {})
            entities[url] = list(kws.keys()) if isinstance(kws, dict) else list(kws)
            
    return entities

def write_link_anchors(candidates: List[Dict], pages: List[Dict], page_text: Dict) -> List[Dict]:
    """Take raw link candidates and write suggested anchors + reasons."""
    recommendations = []
    
    if model_available():
        for i in range(0, len(candidates), 3):
            batch = candidates[i:i+3]
            prompt_parts = ""
            for src in batch:
                src_url = src["source"]
                src_title = next((p["title"] for p in pages if p["url"] == src_url), src_url)
                
                for tgt in src.get("candidates", []):
                    tgt_url = tgt["target"]
                    tgt_title = next((p["title"] for p in pages if p["url"] == tgt_url), tgt_url)
                    prompt_parts += f"Source URL: {src_url}\nSource Title: {src_title}\n"
                    prompt_parts += f"Target URL: {tgt_url}\nTarget Title: {tgt_title}\n"
                    prompt_parts += f"Shared Topics: {tgt.get('shared_topics', [])}\n\n"
                    
            prompt = (
                "Write a descriptive anchor text (3-7 words) for each link. The anchor should describe the TARGET page naturally. "
                "Never use 'click here', 'read more', or generic phrases.\n"
                "Return exactly a JSON array: [{\"source\": \"url\", \"target\": \"url\", \"anchor\": \"text\", \"reason\": \"one line why\"}]\n\n"
                + prompt_parts
            )
            
            try:
                response = model_generate(prompt)
                parsed = get_client().extract_json(response)
                
                if isinstance(parsed, list):
                    for rec in parsed:
                        if "source" in rec and "target" in rec and "anchor" in rec:
                            # Map relatedness back
                            tgt_data = None
                            src_data = next((s for s in batch if s["source"] == rec["source"]), None)
                            if src_data:
                                tgt_data = next((t for t in src_data["candidates"] if t["target"] == rec["target"]), None)
                                
                            if tgt_data:
                                recommendations.append({
                                    "source": rec["source"],
                                    "target": rec["target"],
                                    "suggested_anchor": rec["anchor"],
                                    "relatedness": tgt_data["relatedness"],
                                    "reason": rec.get("reason", "Topically relevant")
                                })
            except Exception as e:
                print(f"[Warning] Failed to write link anchors batch: {e}")

    # Fallback for missing
    rec_pairs = {(r["source"], r["target"]) for r in recommendations}
    for src in candidates:
        src_url = src["source"]
        for tgt in src.get("candidates", []):
            tgt_url = tgt["target"]
            if (src_url, tgt_url) not in rec_pairs:
                reason = "shared topics: " + ", ".join(tgt.get("shared_topics", [])[:2])
                anchor = tgt.get("suggested_anchor")
                if not anchor:
                    tgt_title = next((p["title"] for p in pages if p["url"] == tgt_url), tgt_url)
                    anchor = tgt_title
                    
                recommendations.append({
                    "source": src_url,
                    "target": tgt_url,
                    "suggested_anchor": anchor,
                    "relatedness": tgt.get("relatedness", 0.0),
                    "reason": reason
                })
                
    return recommendations

def enrich_analysis(analysis_result: Dict, pages: List[Dict], page_text: Dict, progress_callback=None) -> Dict:
    """Run all enrichment steps in order. Main entry point."""
    if progress_callback is None:
        progress_callback = lambda stage, detail: None
        
    start_calls = get_client().call_count
    page_keywords = analysis_result.get("page_keywords", {})
    
    # 1. Name clusters
    clusters = analysis_result.get("topical_clusters", [])
    cluster_names = name_clusters(clusters, page_keywords)
    progress_callback("naming_clusters", f"{len(cluster_names)} clusters named")
    
    # 2. Extract entities
    entities = extract_entities_batch(pages, page_text, page_keywords)
    progress_callback("extracting_entities", f"{len(entities)} pages processed")
    
    # 3. Write anchors
    candidates = analysis_result.get("raw_link_candidates", [])
    recommendations = write_link_anchors(candidates, pages, page_text)
    progress_callback("writing_anchors", f"{len(recommendations)} recommendations written")
    
    return {
        "cluster_names": cluster_names,
        "entities": entities,
        "recommendations": recommendations,
        "model_calls": get_client().call_count - start_calls
    }
