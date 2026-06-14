# Link Intel Suite — Internal Linking Intelligence Engine

## Quick Start

### Prerequisites
- Python 3.10+
- Ollama (optional, for model enrichment)

### Install
```
cd link-intel-suite
pip install mcp
```

### Run
```
# Full pipeline with dashboard
python run.py ../sample-export/
# Then open http://localhost:7700

# Without dashboard
python run.py ../sample-export/ --no-dashboard

# With Claude Code plugin
/link-intel ../sample-export/
```

### Outputs
- outputs/report.json — machine-readable report (matches report.schema.json)
- outputs/report.html — client-ready standalone report

### Validate
```
python scripts/validate.py
```

## Architecture
- linkintel/analyzer.py — deterministic analysis (graph, anchors, clusters, relatedness)
- linkintel/tfidf.py — TF-IDF module for clustering and similarity
- linkintel/model_client.py — Ollama API client with fallback
- linkintel/enrichment.py — model-powered enrichment (cluster names, entities, anchors)
- mcp/server.py — MCP tools + live dashboard server
- dashboard/ — live cockpit (HTML + JS)

## Model
Uses any free Ollama model. Set via LI_MODEL or RADAR_MODEL env var.
Default: gpt-oss:20b-cloud

Works fully without a model (deterministic fallback for all model steps).
