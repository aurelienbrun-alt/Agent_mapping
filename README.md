# Enterprise Regulatory Framework Mapper - Azure OpenAI / ENISA edition

This version removes Gemini dependencies and uses Azure OpenAI only. It is designed for enterprise-style regulatory crosswalks between two Excel frameworks, using ENISA categories as the common taxonomy.

## What changed in this version

### 1. ENISA category harmonization before cache creation

When no processed framework cache exists, the agent reads both source Excel files and verifies whether the configured category column uses the ENISA category taxonomy contained in `data/enisa_categories.xlsx`.

If a requirement has a category that is not part of the ENISA taxonomy, the agent classifies the requirement into the most appropriate ENISA category. It first applies deterministic rules and, when needed, calls Azure OpenAI. No subcategory is used.

The harmonization cache is saved per framework in:

```text
docs/cache/<framework_cache_key>/category_harmonization.json
```

This prevents mapping errors caused by category drift, for example mapping privileged account requirements into Awareness and Training instead of Access control.

### 2. Stronger candidate selection heuristic

Embeddings are now treated as a retrieval mechanism, not as proof of equivalence. The final candidate ranking combines:

| Signal | Default weight | Purpose |
|---|---:|---|
| Semantic similarity | 0.35 | Recalls broadly related candidates. |
| Structured field similarity | 0.25 | Compares actor, action, object, evidence and control type. |
| Action/object similarity | 0.25 | Forces alignment of the main obligation and controlled object. |
| Keyword/BM25 similarity | 0.10 | Helps with discriminant terms and acronyms. |
| Control type similarity | 0.05 | Avoids mixing training, access control, logging, incident response, etc. |

The key enterprise rule is the object/action gate:

```text
A mapping cannot be Exact match or high Partial unless the target covers the same main action and the same main object.
```

This directly addresses false positives such as:

```text
administrator account access-control obligation -> awareness/training control
```

Such mappings are downgraded to Indirect or Gap unless the target also explicitly imposes the same access-control obligation.

### 3. Better LLM-as-judge

The pairwise judge must return dimension-level analysis:

```text
actor, action, object, scope, condition, deadline, evidence, control_type, granularity
```

The final judge then reviews category-level mappings and corrects over-optimistic Exact matches. The final judge is intentionally stricter than the retrieval step.

Recommended Azure deployments:

| Use | Cost-efficient | Better quality | High assurance |
|---|---|---|---|
| Atomization / field extraction | gpt-4.1-nano | gpt-4.1-mini | gpt-5.4-nano or stronger if available |
| Category harmonization | gpt-4.1-nano | gpt-4.1-mini | gpt-5.4-nano |
| Pairwise mapping | gpt-4.1-nano | gpt-4.1-mini | gpt-5.4-nano |
| Final LLM judge | gpt-4.1-mini | gpt-5.4-nano | gpt-5.4 or stronger reasoning model |
| Embeddings | text-embedding-3-small, 512 dimensions | text-embedding-3-large | text-embedding-3-large |

Model availability and deployment names depend on your Azure region and quota. The value in `.env` must be the Azure deployment name, not necessarily the model id.

Microsoft documents that embeddings represent semantic meaning and similarity in vector space, but this mapper adds structured and action/object gates because semantic similarity alone is not sufficient for regulatory equivalence.

## Input Excel format

Place the frameworks in `data/` and configure the columns in `.env`:

```env
FRAMEWORK_A_NAME=NIS2_France
FRAMEWORK_A_FILE=data/framework_a.xlsx
A_ID_COLUMN=ID
A_TITLE_COLUMN=Title
A_REQUIREMENT_COLUMN=Requirement
A_CATEGORY_COLUMN=Category

FRAMEWORK_B_NAME=NIS2_Belgique
FRAMEWORK_B_FILE=data/framework_b.xlsx
B_ID_COLUMN=ID
B_TITLE_COLUMN=Title
B_REQUIREMENT_COLUMN=Requirement
B_CATEGORY_COLUMN=Category
```

Subcategories are intentionally ignored in this edition.

## ENISA categories

The ENISA category file is:

```env
ENISA_CATEGORY_FILE=data/enisa_categories.xlsx
ENISA_CATEGORY_SHEET=Catégories ENISA
```

Expected columns:

```text
Category
Sub category
```

Only the `Category` column is used for matching scope. `Sub category` can help the LLM understand the taxonomy, but it does not create a matching filter.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Azure configuration

Set the Azure OpenAI resource endpoint, not a Foundry project endpoint:

```env
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE-NAME.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
```

Do not use:

```text
https://...services.ai.azure.com/api/projects/...
```

Configure deployments:

```env
AZURE_OPENAI_TEXT_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_CATEGORY_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=512
```

## Run

```powershell
python run_agent.py
```

The output workbook is written to:

```text
output/
```

Logs are written to:

```text
logs/
reports/
```

## Recommended first run

For a first run after changing category columns, prompts, models or embeddings:

```env
REBUILD_CACHE=true
```

After a successful run:

```env
REBUILD_CACHE=false
```

## Cache behavior

The default cache mode is file-name based:

```env
CACHE_KEY_MODE=file_name
```

This creates folders such as:

```text
docs/cache/NIS2_France/
docs/cache/NIS2_Belgique/
```

Cached files include:

```text
category_harmonization.json
atomized_requirements.json
atomic_requirements_with_fields.json
atomic_requirements.json
processing_report.json
```

If you rename the Excel files, the cache folder name changes too.

## Output workbook structure

| Sheet | Purpose |
|---|---|
| README | Explains scoring, category harmonization and interpretation. |
| Dashboard | Executive KPIs and charts. |
| Fr 1 -> Fr2 | Parent-level mapping from framework 1 to framework 2. No atom wording. |
| Fr 2 -> Fr1 | Parent-level mapping from framework 2 to framework 1. No atom wording. |
| Coverage by Category | Coverage and review priority by ENISA category. |
| Category Quality | Traceability and category coverage diagnostics. |
| Atomic Fr 1 -> Fr2 | Detailed evidence trail. |
| Atomic Fr 2 -> Fr1 | Detailed evidence trail. |

## Parent output design

Parent sheets do not expose technical atomization details. They include:

```text
Source regulation
Source control ID
Source requirement
ENISA category
Target regulation
Target control ID(s)
Target requirement(s)
Coverage relationship
Coverage level
Match type
Gap - aspects not covered by target regulation
Review priority
Mapping risk
```

There are no separate `Justification` or `Recommendation` columns in the parent sheets. The single `Gap` column contains precise residual coverage information. Detailed justifications, recommendations, dimension scores and candidate diagnostics are kept in the atomic sheets.

## Coverage scoring methodology

The `Coverage Level` measures how much of the source requirement is covered by the target regulation. It is not a confidence score.

| Relationship | Coverage | Meaning |
|---|---:|---|
| Exact match | 100 | Same actor, action, object, scope, conditions and evidence expectations. |
| Mostly covered | 75 | Same core obligation, but one material dimension is narrower or less explicit. |
| Partially covered | 50 | Same general obligation area, but important elements are missing. |
| Indirect / supportive | 25 | Related or supportive but not the same direct obligation. |
| Gap | 0 | No sufficient target coverage identified. |

Parent-level coverage is aggregated from the detailed requirement-level analysis, so parent scores can be non-standard values such as 62.5.

## Why this improves performance

The previous approach could return false positives because embeddings retrieved candidates that were semantically close but regulatory-different. For example, access-control obligations and awareness-training obligations can both mention privileged users. This version separates:

```text
retrieval similarity
from
regulatory equivalence
```

The retrieval step maximizes recall. The judge and post-processing gates decide equivalence using action/object/control-type alignment.

## Troubleshooting

### The agent still refines categories incorrectly

Set:

```env
CATEGORY_HARMONIZATION_FORCE=true
REBUILD_CACHE=true
```

Then rerun. After a good run, set both back to:

```env
CATEGORY_HARMONIZATION_FORCE=false
REBUILD_CACHE=false
```

### The run is too expensive

Use:

```env
AZURE_OPENAI_TEXT_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_CATEGORY_DEPLOYMENT=gpt-4.1-nano
AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-nano
TOP_K_CANDIDATES=5
FINAL_JUDGE_ONLY_AMBIGUOUS=true
```

### The final judge misses errors

Use a stronger judge deployment:

```env
AZURE_OPENAI_JUDGE_DEPLOYMENT=gpt-4.1-mini
FINAL_JUDGE_ONLY_AMBIGUOUS=false
```

For maximum assurance, deploy a stronger reasoning-capable model for the final judge only, if available in your Azure region.

## v3.2 - Autonomous category guardrails

The recommended production mode is now `MATCH_SCOPE=soft_enisa`. In this mode, ENISA categories are **advisory signals**, not hard filters:

- a correct category boosts candidate ranking;
- secondary categories provide rescue paths for multi-domain requirements;
- a wrong category does not prevent semantic, keyword, structured-field and action/object matching from finding a candidate.

### Category templates

`data/enisa_categories.xlsx` now contains enriched ENISA category cards with definitions, positive/negative keywords, typical actions, typical objects, examples, counterexamples and strict rules.

`config/category_overrides.xlsx` contains editable deterministic rules for high-impact patterns such as:

- remote access / accès distant -> Access control, with Cryptography secondary when cryptographic mechanisms are present;
- privileged accounts / least privilege -> Access control;
- MCO/MCS / patching / vulnerability -> category 6;
- PCA/PRA / backups -> Business continuity and crisis management;
- suppliers / prestataires -> Supply chain security.

### Repair categories without rebuilding the cache

To repair category metadata in existing caches without rerunning atomization, field extraction or embeddings:

```powershell
python tools/repair_categories.py --framework both
```

Then rerun the mapping normally:

```powershell
python run_agent.py
```

If you only want to repair weak categories:

```powershell
python tools/repair_categories.py --framework both --only-low-confidence
```

If you changed `data/enisa_categories.xlsx` or `config/category_overrides.xlsx` and want to ignore previous category decisions:

```powershell
python tools/repair_categories.py --framework both --force
```

### Quality reports

Each category repair writes:

- `reports/category_quality_<framework>.xlsx`
- `docs/cache/<framework>/category_quality_report.json`

Use these reports to inspect low-confidence assignments, changed assignments and multi-domain requirements. The mapping still runs autonomously; low confidence categories trigger the soft matching behaviour rather than blocking the run.

## v3.3 performance mode

Long mapping runs are mostly caused by pairwise LLM judge calls. v3.3 adds four safeguards:

1. **Decision cache** in `docs/cache/mapping_decisions_cache.jsonl`.
2. **Parallel LLM calls** with `MAX_CONCURRENT_LLM_CALLS`.
3. **Smaller LLM prompts** with `LLM_TOP_K_CANDIDATES`.
4. **Ambiguous-only final judge** with `FINAL_JUDGE_ONLY_AMBIGUOUS=true`.

Recommended normal run:

```env
REBUILD_CACHE=false
MATCH_SCOPE=soft_enisa
TOP_K_CANDIDATES=15
LLM_TOP_K_CANDIDATES=6
MAX_CONCURRENT_LLM_CALLS=4
ENABLE_MAPPING_DECISION_CACHE=true
LLM_SELF_REVIEW=false
LLM_SELF_REVIEW_ROUNDS=0
LLM_REPEAT_ON_LOW_CONFIDENCE=true
LLM_CONFIDENCE_THRESHOLD=0.65
RUN_FINAL_LLM_JUDGE=true
FINAL_JUDGE_ONLY_AMBIGUOUS=true
FINAL_JUDGE_BATCH_SIZE=25
```

If Azure rate limits the run, lower:

```env
MAX_CONCURRENT_LLM_CALLS=2
```

For a final high-quality run:

```env
LLM_SELF_REVIEW=true
LLM_SELF_REVIEW_ROUNDS=1
MAX_CONCURRENT_LLM_CALLS=3
FINAL_JUDGE_ONLY_AMBIGUOUS=true
```

If you modify only output formatting, rerun with the same cache and the same candidates: previous LLM mapping decisions should be reused automatically.

## v3.4 - Parent gap synthesis and run visibility

This version improves the parent-level gap column and makes the run easier to follow from the terminal.

### Parent gap improvements
- Pairwise LLM now returns `gap_items` with `dimension`, `gap`, `target_coverage`, and `severity`.
- Parent output aggregates these structured items into a concise but complete residual gap analysis.
- The parent gap cell is no longer hard-limited to a fixed number of bullets.
- Generic/debug text is removed from parent gaps.
- Near-duplicate residual gaps are merged.
- Gaps are grouped by regulatory dimension and severity.

### Run visibility
The terminal now shows high-level stages:
1. Preprocessing and cache loading
2. Directional mapping
3. Final judge
4. Excel workbook writing
5. Log analysis report writing

The final judge now displays a progress bar by batch.

## v3.6 - Less gaps / relation taxonomy

Recommended production settings:

```env
MATCH_SCOPE=soft_enisa
USE_KEYWORD_MATCHING=false
USE_LLM_KEYWORD_NORMALIZATION=false
WEIGHT_KEYWORD=0.00
WEIGHT_SEMANTIC=0.45
WEIGHT_STRUCTURED=0.30
WEIGHT_ACTION_OBJECT=0.20
WEIGHT_CATEGORY_PRIOR=0.03
MIN_CANDIDATE_COMBINED_SCORE=0.04
OBJECT_ACTION_GATE_MODE=score_cap
OBJECT_ACTION_CAP_75_THRESHOLD=0.25
OBJECT_ACTION_CAP_25_THRESHOLD=0.10
ENABLE_CANDIDATE_RESCUE=true
ENABLE_OBVIOUS_GAP_SHORTCUT=false
ENABLE_PARENT_GAP_LLM_SYNTHESIS=true
```

The category step remains part of the pipeline, but it cannot break the run: `soft_enisa` uses global retrieval and treats category as a confidence-weighted prior only.

The mapping now distinguishes `true_gap`, `partial_gap`, `implementation_detail_gap`, `indirect_support_gap`, `conflict_gap`, and `none`.

---

# v4 production hardening notes

## Why this version is more usable

This version implements four production safeguards designed to make the agent usable in a real mapping workflow:

1. **Framework cache validation**
   - `STRICT_INPUT_CACHE_VALIDATION=true` prevents the agent from silently reusing a cache built from another Excel file.
   - This fixes the failure mode where a test framework is accidentally mapped against a previous full-framework cache.

2. **Soft ENISA category matching**
   - `MATCH_SCOPE=soft_enisa` is the recommended default.
   - ENISA category is used as a ranking prior, not as a hard filter.
   - A bad category can improve or lower ranking slightly, but it cannot prevent global semantic/structured retrieval.

3. **Controlled relation taxonomy**
   - Atomic and parent sheets use stable relationship labels:
     - Exact coverage
     - Mostly covered
     - Partially covered
     - Implementation details missing
     - Indirectly covered
     - Not covered
     - Conflicting
   - Raw LLM labels such as `weak`, `approximate`, `same_objective_different_scope`, or numeric strings are normalized before export.

4. **Parent gap synthesis and validation**
   - Parent gap text is produced from structured atomic residual gap items.
   - Optional LLM parent synthesis can be enabled with `ENABLE_PARENT_GAP_LLM_SYNTHESIS=true`.
   - The parent gap classifier distinguishes:
     - `true_gap`
     - `partial_gap`
     - `implementation_detail_gap`
     - `indirect_support_gap`
     - `conflict_gap`
     - `none`

## Recommended `.env` settings

For a normal production run:

```env
REBUILD_CACHE=false
STRICT_INPUT_CACHE_VALIDATION=true
VALIDATE_OUTPUT_TARGET_IDS=true
INVALID_TARGET_ID_POLICY=raise

MATCH_SCOPE=soft_enisa
USE_KEYWORD_MATCHING=false
USE_LLM_KEYWORD_NORMALIZATION=false
WEIGHT_KEYWORD=0.00

TOP_K_CANDIDATES=15
LLM_TOP_K_CANDIDATES=8
MIN_CANDIDATE_COMBINED_SCORE=0.04

ENFORCE_OBJECT_ACTION_GATE=true
OBJECT_ACTION_GATE_MODE=score_cap
OBJECT_ACTION_CAP_75_THRESHOLD=0.25
OBJECT_ACTION_CAP_25_THRESHOLD=0.10

ENABLE_CANDIDATE_RESCUE=true
STRONG_CANDIDATE_UPGRADE_ENABLED=true

RUN_FINAL_LLM_JUDGE=true
FINAL_JUDGE_ONLY_AMBIGUOUS=true
ENABLE_PARENT_GAP_LLM_SYNTHESIS=true
```

For a fast diagnostic run:

```env
RUN_FINAL_LLM_JUDGE=false
ENABLE_PARENT_GAP_LLM_SYNTHESIS=false
LLM_REPEAT_ON_LOW_CONFIDENCE=false
MAX_CONCURRENT_LLM_CALLS=4
```

## When changing only categories

If you update `data/enisa_categories.xlsx` or `config/category_overrides.xlsx`, you do not need to redo atomization and fields. Run:

```powershell
python tools/repair_categories.py --framework both --force
python run_agent.py
```

## When changing input Excel files

If you change `FRAMEWORK_A_FILE` or `FRAMEWORK_B_FILE`, the v4 cache validator will reject stale caches by default. If you intentionally want to reuse old caches, set:

```env
STRICT_INPUT_CACHE_VALIDATION=false
```

This is not recommended for production, because it can produce outputs with target IDs not present in the current input.

## Troubleshooting stale target IDs

If the run fails with invalid target IDs, delete only the mapping-decision caches, not the framework atomization cache:

```powershell
Remove-Item .\docs\cache\mapping_decisions_cache.jsonl -ErrorAction SilentlyContinue
Remove-Item .\docs\cache\parent_gap_synthesis\parent_gap_synthesis_cache.jsonl -ErrorAction SilentlyContinue
python run_agent.py
```
