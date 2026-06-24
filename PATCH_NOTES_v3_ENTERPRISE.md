# Patch notes v3 - Enterprise Azure OpenAI / ENISA edition

## Removed
- Removed Gemini client and Gemini configuration paths.
- Removed subcategory matching. The mapper now uses ENISA category scope only.

## Added
- ENISA category harmonization step before framework cache creation.
- Azure OpenAI-only execution path.
- Stronger candidate ranking with action/object and control-type alignment.
- Post-LLM object/action gate to prevent false Exact matches from semantic similarity alone.
- Dimension-level LLM judge output: actor, action, object, scope, condition, deadline, evidence, control_type, granularity.
- Professional workbook output generated from code, with dashboard, charts, category coverage, clean parent sheets and detailed atomic evidence sheets.
- Parent sheets no longer expose atomization details or separate Justification/Recommendation columns.

## New key configuration
- ENABLE_CATEGORY_HARMONIZATION=true
- ENISA_CATEGORY_FILE=data/enisa_categories.xlsx
- MATCH_SCOPE=same_enisa_category
- WEIGHT_ACTION_OBJECT=0.25
- ENFORCE_OBJECT_ACTION_GATE=true
- AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-mini

## Recommended migration
1. Replace the whole project folder with this version.
2. Put your two framework Excel files in `data/`.
3. Configure `.env` columns and Azure deployments.
4. Run once with `REBUILD_CACHE=true`.
5. Then set `REBUILD_CACHE=false` for future runs.
