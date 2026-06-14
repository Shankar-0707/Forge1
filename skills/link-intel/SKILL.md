---
name: link-intel-suite
description: >
  Analyze a website's internal linking and topical authority from a Screaming Frog export.
  Use this whenever the user wants to map internal links, find orphan pages, audit anchor
  text, build topical clusters / an entity graph, or get contextual internal-link
  recommendations from a Screaming Frog export (internal_html.csv + all_inlinks.csv +
  page text/). Trigger it for "analyze the internal linking", "find orphan pages",
  "build the link graph", "what should this page link to", "/link-intel", or any request
  to process a crawl into an internal-linking + topical-authority report. It runs an
  autonomous pipeline through the link-intel-suite MCP server and renders a live dashboard
  plus an exportable report.
---

# Link Intel Suite - orchestrator

Given a Screaming Frog export folder, run an autonomous internal-linking + topical-authority
analysis and ship a prioritized report plus contextual link recommendations. A live
dashboard shows the work at http://localhost:7700.

The real work runs through tools on the **link-intel-suite MCP server**. Delegate focused
steps to the sub-agents so each stays small (this also keeps you inside free-tier quota).
Do the graph, orphan detection, and anchor classification in **code** (the analyzer module
is deterministic). Use TF-IDF and weighted Jaccard similarity for clustering and relatedness.
Use the LLM model only for **entity extraction, naming clusters, and writing the contextual
link suggestions + anchors**.

## Pipeline (run in order)

1. **Ingest + graph.** Delegate to the `graph-agent` -> MCP `load(export_dir)` then
   `graph_stats()`. Confirm pages, internal-link count, orphan pages, deepest pages,
   broken/redirect/nofollow internal links. Tell the user to open http://localhost:7700.
   *Note: Use `Unique Inlinks` for orphan page detection.*

2. **Anchors.** Delegate to the `anchor-agent` -> MCP `anchors()`. Review generic,
   empty/image-only, and over-optimized exact-match anchors. Over-optimized anchors
   require a share of >= 0.6 AND a count of >= 10.

3. **Topics + entities.** Delegate to the `topic-agent`. Call MCP `topics()` to compute the
   clusters using deterministic **TF-IDF with cosine similarity**, then have the model
   **name** each cluster from its keywords/pages (batched 8 clusters per API call) and call
   `topics({key: name, ...})`. Then extract 5-8 key **entities** per page from the page
   text (batched 5 pages per API call) and call `entities({url: [entity, ...]})` to
   sharpen the entity graph. *Note: Weighted Jaccard with IDF scores must be used for relatedness.*

4. **Contextual link recommendations.** Delegate to the `linker-agent`. For each important page,
   take the deterministic candidates and have the model **write a specific, descriptive anchor**
   for each suggestion. *Note: Prioritize orphan or under-linked pages as recommendation targets!*
   Call MCP `recommend([{source, target, suggested_anchor, relatedness, reason}, ...])`.

5. **Deliver.** Delegate to the `reporter` -> MCP `write_report()` then `export_report()`.
   Run `python scripts/validate.py` to ensure the generated `outputs/report.json` passes schema
   validation checks!

## Output contract
The run must end with `outputs/report.json` matching `report.schema.json`. The grader reads
it. Required top-level keys: `site`, `pages_crawled`, `summary`, `link_graph`,
`anchor_text`, `topical_clusters`, `entity_graph`, `link_recommendations`, `run_meta`.

## Notes
- Never feed the whole crawl to the model. Detect graph/anchor issues in code.
- Batch model API calls (e.g. 5 pages per prompt, 8 clusters per prompt) to drastically speed
  up execution and save on quota limits.
- The pipeline MUST fall back to deterministic values (like title tags or TF-IDF keywords)
  if the LLM fails to return valid JSON, ensuring the report always successfully generates!
- Be honest in the run summary about which parts are model-written vs deterministic.
