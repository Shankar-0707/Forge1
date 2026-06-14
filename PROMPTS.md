# PROMPTS.md - my key prompts log

Keep the handful of prompts that actually moved the build. Not every message - the ones that
mattered: the system/sub-agent prompts, the ones you iterated on, the "this finally worked"
moment. Paste them here MANUALLY as you go.

Why manual? Some free Ollama cloud models do not save a local session log, so an auto audit
log may be empty. That is fine and expected (see the brief's Model Fairness section). What
guarantees your process is judged fairly is: the working plugin + reproducible report.json,
incremental git commits, this PROMPTS.md, and a short DECISIONS.md. Keep these up to date.

Format per entry:
- **Prompt** (paste it)
- **For:** what you were trying to do
- **Revised?** did you have to change it, and why

---

## My prompts

- **Prompt:** "For each page below, extract 5-8 key entities (services, technologies, concepts). Return JSON: {\"url1\": [\"entity1\", ...], ...}\n\nPages:\n" + page_details
- **For:** Extracting entities per page.
- **Revised?** Yes. Added strict JSON formatting and limited to 5-8 entities to keep outputs focused and prevent hallucinated fields. Batched 5 pages per prompt to save quota.

- **Prompt:** "Given these topic clusters with their keywords, give each a short descriptive name (2-5 words). Return JSON: {\"key1\": \"Name 1\", ...}\n\nClusters:\n" + cluster_details
- **For:** Giving human-readable names to TF-IDF clusters.
- **Revised?** Yes. Added the 2-5 words constraint to ensure names fit neatly in the dashboard UI and report.

- **Prompt:** "For each link target, suggest a 2-5 word anchor text and give a 1 sentence reason why. Return JSON: [{\"source\": url, \"target\": url, \"suggested_anchor\": \"...\", \"reason\": \"...\"}, ...]\n\nCandidates:\n" + prompt_parts
- **For:** Writing contextual link recommendations and anchors.
- **Revised?** Yes. Reduced batch size to 3 candidate pairs per prompt because the model struggled to follow instructions and format output correctly for larger batches.
