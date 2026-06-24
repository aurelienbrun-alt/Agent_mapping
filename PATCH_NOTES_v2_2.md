# Patch v2.2 - quality fixes

Replace these files in your current project:

- `src/matching.py`
- `src/output_writer.py`
- `src/final_judge.py`
- `src/preprocessing.py`

Then update only the prompt section of your `.env` with the prompt block from this package. Do not overwrite your API key, file paths or column names unless you want to reset them.

## What this fixes

1. Stricter atomization prompt:
   - split multiple actions such as adopt/document, identify/report, establish/communicate/coordinate;
   - make atomic requirements more autonomous;
   - pass ID/title/category/subcategory as context to the atomization prompt.

2. Mapping consistency:
   - no `Gap` with coverage > 0;
   - no `Exact match` below 100;
   - no technical API stack traces in the Excel output;
   - heuristic fallback is capped as `Partial` and marked for manual review.

3. Final judge:
   - final judge corrections are now actually applied to decisions, not only appended as notes.

4. Excel output:
   - removes duplicate sheets like `Dashboard (2)` and sheet names with trailing spaces like `Dashboard `;
   - unmerges old template cells before writing;
   - adds a `Parent coverage` sheet that aggregates atomic mappings back to original control IDs.

## Important after applying

Because the atomization prompt changed, set:

```env
REBUILD_CACHE=true
```

for the first run after patching. After the run, you can set it back to:

```env
REBUILD_CACHE=false
```
