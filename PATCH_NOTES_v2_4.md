# v2.4 - Cache checkpoint/resume

This patch fixes cache behavior when a run crashes during preprocessing.

## Replace
- `src/cache.py`
- `src/preprocessing.py`

## What changed
The agent now writes intermediate cache files:
- `atomized_requirements.json` after atomization
- `atomic_requirements_with_fields.json` during field extraction and embeddings
- `atomic_requirements.json` only when the framework is fully processed

If the run crashes during field extraction or embeddings, the next run resumes from the last checkpoint instead of restarting the whole framework.

## Important .env values
Use:

```env
REBUILD_CACHE=false
DOCS_CACHE_DIR=docs/cache
```

Set `REBUILD_CACHE=true` only when you intentionally want to recompute atomization/extraction/embeddings.
