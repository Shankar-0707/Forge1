# DECISIONS.md - decision & learnings log

A short running note of the real choices you made: what you tried, what failed and why, what
you changed. This is your engineering judgement on the record - it is what separates a builder
from a button-presser, and it is graded (from git history + this file + PROMPTS.md, NOT from
an auto audit log, which may be empty on cloud models).

Append a 1-2 line entry whenever you make a real decision or hit/fix a wall. Add a timestamp.

Format:
`[HH:MM] <decision or problem> -> <what you did and why>`

---

## My log
- `[09:15]` Decision: TF-IDF clustering over URL path segments -> Why: Path segments generated 33 clusters, many of which were unrelated. TF-IDF clustering with cosine similarity is much more accurate and works on any site structure.
- `[09:45]` Decision: Deterministic fallback for all model steps -> Why: Ensures the pipeline can always finish and outputs/report.json is always valid, even if the LLM API times out or fails to return valid JSON.
- `[10:10]` Decision: Batch model calls instead of one-per-page -> Why: Significantly saves on API quota and is drastically faster. Batched 5 entities per call, 8 clusters per call.
- `[10:30]` Decision: Weighted Jaccard over plain Jaccard -> Why: Plain Jaccard treats common words equally. Weighting with IDF scores ensures that rare shared terms form much stronger relatedness bonds than generic shared terms.
- `[10:50]` Decision: Prioritize orphan/under-linked pages in recommendations -> Why: The linker agent targets pages that actually need link equity rather than randomly connecting highly-linked hub pages. This fixes real SEO gaps.
- `[11:15]` Fixed Bug: Crash on list severity check -> Why: `g['redirect_internal_links']` returned a list. Updated `mcp/server.py` to use `len()` when rendering the list size for severity threshold checks.
