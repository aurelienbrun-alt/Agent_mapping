# Patch v2.5 - Cache reuse by file name

This patch adds a configurable cache key strategy.

## New `.env` option

```env
CACHE_KEY_MODE=hash
```

Allowed values:

- `hash`: default and safest. The cache folder changes when the Excel file content, prompts, models, column names, or relevant options change.
- `file_name`: the cache folder is based only on the Excel filename without extension, for example `docs/cache/NIS2_Belgique`.
- `framework_name`: the cache folder is based only on `FRAMEWORK_A_NAME` / `FRAMEWORK_B_NAME`.

## Recommended setting for easier reuse

```env
REBUILD_CACHE=false
CACHE_KEY_MODE=file_name
```

## Warning

`file_name` can reuse stale cache if you modify the Excel content, prompts, extraction options, or model but keep the same file name. Use `REBUILD_CACHE=true` once when you intentionally want to refresh the cache.

## Added logs

The agent now logs:

- `cache.lookup`
- cache mode
- expected cache directory
- whether `REBUILD_CACHE` is enabled
