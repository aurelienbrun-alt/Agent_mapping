# Patch notes — Web application

A browser front end for the regulatory framework mapper. Internal analysts can now
run NIS2 mappings, import their own frameworks, browse/visualize past results, and
build baselines from a web UI instead of editing `.env` and running `run_agent.py`
on the command line.

The existing pipeline in `src/` is reused **unchanged** except for a single additive
hook (see below). Everything web-specific lives under `webapp/`.

---

## 1. Architecture

- **Backend:** FastAPI (Python). Serves a REST API under `/api` and, in production,
  the built React app from the same origin.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS v4 (single-page app).
- **Packaging:** one multi-stage `Dockerfile`, started with a plain
  `docker run -p 8080:8080` (no docker-compose).
- **Jobs:** long mappings/baselines run in a background thread; the UI polls for
  status (no progress bar exposed in v1).

```
webapp/
  core/      # UI-agnostic business logic (wraps src/ unchanged)
  api/       # FastAPI REST layer (routes, request/response schemas, deps)
  frontend/  # React + Vite + TypeScript + Tailwind SPA
  main.py    # `python -m webapp.main` -> uvicorn launcher
```

## 2. The only change to existing pipeline code

- **`src/config.py`** — `load_config()` gained an optional `overrides: dict` argument.
  When present, those values take precedence over `.env` / environment for that call.
  This is the single seam the web app uses to inject per-request Azure credentials and
  the selected source/target frameworks **without writing to `.env`**. Empty/missing
  override values fall back to `.env`, so existing CLI behaviour is unchanged.

No other `src/` file was modified. All mapping logic, scoring, and Excel output are
the same code paths used by `run_agent.py`.

## 3. Features

### Settings (Azure-only in v1)
- Gear icon → modal for **Azure endpoint + API version + API key**, with
  **Test connection** and **Save**.
- The API key is **stored only in the browser** (`localStorage`) and sent on each
  request as headers (`X-Azure-Api-Key`, `X-Azure-Endpoint`, `X-Azure-Api-Version`).
  It is **never written to disk or persisted server-side**.
- Model/deployment choice is intentionally not exposed — deployments stay in `.env`.

### New Mapping
- Pick a **Source** and a **Target** framework from cards, then **Lancer l'analyse**.
- **Entity type selector** — checkboxes for *Entité Essentielle* / *Entité Importante*
  (both pre-ticked; at least one required). NIS2 requirements can apply to one tier
  and not the other; the selection is carried through the run for downstream filtering.
- Mapping is **bidirectional** (A→B and B→A).
- On completion: KPI summary (average coverage, decisions analysed, gaps) and
  **download as Excel** (full detail) or **PDF** (executive summary).

### Frameworks catalog
- Built-in: **Belgique CyFun 2025** (218 requirements) and **France 2.3** (152).
- **Coming-soon** entries shown as greyed, non-clickable "Bientôt" cards:
  Pays-Bas CBw NIS2, Italie FNSC 2025, Grèce Réf. 1689. Activating one later is just
  setting its file path and `available=True` — no other change needed.
- The selected framework's file is mapped onto the pipeline's A/B slots at run time;
  any other files sitting in `data/` are simply not referenced.

### Custom framework import
- Upload an `.xlsx` from the **"Importer un framework"** card or the sidebar
  **Importer Framework** action.
- The file must contain four columns (header casing is ignored):
  - **ID** — unique identifier of the requirement
  - **Title** — title of the control / framework (e.g. *CyFun 2025*)
  - **Requirement** — the detailed requirement text
  - **Category** — the requirement's category in that framework
- If any column is missing, the import is rejected with a clear, multi-line message
  listing the four required columns (with descriptions) and what was found in the file.
- Valid imports are **persisted** to `data/custom/` (the Excel file +
  `registry.json`) and immediately become selectable like the built-ins. Custom
  cards carry a delete (×); built-ins cannot be deleted.

### Mappings browser + viewer
- Sidebar **"🗂️ Mappings réalisés"** → a page listing the Excel workbooks the agent
  has written to `output/` (most recent first, with date / size / sheet count).
- Each entry can be **downloaded** or **visualized in the browser**: a viewer with
  one tab per worksheet, a sticky-header table, and **"Coverage level" cells colored
  by band** (green ≥ 100, amber ≥ 40, red < 40). The viewer opens on the mapping
  sheet by default. Large sheets are capped at 2000 displayed rows (download for the
  full file).

### Baseline
- After a mapping, tick the **ENISA categories** to include and build the
  consolidated compliance control list (Excel download).

## 4. Security model

- **No server-side storage of Azure credentials.** Key lives in browser
  `localStorage`, travels as request headers, and is used transiently per request.
- **No secret baked into the image.** The Dockerfile sanitizes `.env` (drops the API
  key line) in a throwaway build stage before copying it into the runtime image.
- **Path-safe file access.** The output viewer and downloader only serve `*.xlsx`
  files located directly inside the output directory; traversal (`..`), sub-paths and
  hidden files are rejected. Custom-framework deletion only removes files resolved
  inside `data/custom/`.

## 5. New / changed files

**New — backend (`webapp/`):**
- `main.py`, `api/main.py`, `api/deps.py`, `api/schemas.py`
- `api/routes/`: `frameworks.py`, `categories.py`, `settings.py`, `mappings.py`,
  `baselines.py`, `outputs.py`
- `core/`: `catalog.py`, `framework_import.py`, `config_builder.py`,
  `settings_state.py`, `categories.py`, `jobs.py`, `pipeline_runner.py`,
  `baseline_runner.py`, `pdf_report.py`, `output_browser.py`

**New — frontend (`webapp/frontend/`):**
- `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `index.css`
- `src/App.tsx`, `src/main.tsx`, `src/api/client.ts`
- `src/components/`: `Sidebar.tsx`, `Header.tsx`, `SettingsModal.tsx`,
  `FrameworkCard.tsx`, `ImportModal.tsx`
- `src/pages/`: `NewMapping.tsx`, `Mappings.tsx`, `Baseline.tsx`
- `src/lib/`: `settings.ts`, `appState.tsx`

**New — packaging / tooling:**
- `Dockerfile` (3 stages: build SPA → scrub `.env` → Python runtime)
- `.dockerignore`, `.claude/launch.json` (`nis2-webapp` dev launch config)
- `webapp/README.md`

**Modified (existing files):**
- `src/config.py` — additive `overrides` argument on `load_config()` (only src/ change)
- `requirements.txt` — added `fastapi`, `uvicorn[standard]`, `python-multipart`,
  `reportlab`
- `.gitignore` — ignore runtime data (`data/custom/`)

## 6. API endpoints (under `/api`)

- `GET  /health`
- `GET  /frameworks` · `POST /frameworks/import` · `DELETE /frameworks/{id}`
- `GET  /categories`
- `POST /settings/test`
- `POST /mappings` · `GET /mappings/{job_id}` · `GET /mappings/{job_id}/download?fmt=excel|pdf`
- `POST /baselines` · `GET /baselines/{job_id}` · `GET /baselines/{job_id}/download`
- `GET  /outputs` · `GET /outputs/{name}/view` · `GET /outputs/{name}/download`

## 7. How to run

**Docker (recommended):**
```bash
docker build -t nis2-mapper .
docker run -p 8080:8080 nis2-mapper
# open http://localhost:8080
```
Optional persistence across runs (imported frameworks, outputs, cache):
```bash
docker run -p 8080:8080 \
  -v nis2_custom:/app/data/custom \
  -v nis2_out:/app/output \
  -v nis2_cache:/app/docs/cache \
  nis2-mapper
```

**Local dev:**
```bash
python -m pip install -r requirements.txt
python -m webapp.main                 # API + built SPA on :8080
# in a second terminal, for hot reload:
cd webapp/frontend && npm install && npm run dev   # Vite on :5173, proxies /api
```

## 8. Verification status

- **Verified:** SPA builds clean (`npm run build`); FastAPI serves the API + SPA;
  framework import (validate → persist → select) and column-error handling; mappings
  browser list → in-app viewer (sheet tabs, table, UTF-8 text, coverage coloring);
  output path-safety and header-row detection; New Mapping page renders live cards,
  coming-soon cards, and the entity-type panel.
- **Not yet verified:** a live end-to-end Azure run (needs a real key) and
  `docker build` (Docker daemon was unavailable in the test environment). The code
  paths for both are in place.

## 9. v1 shortcuts and extension seams

These are deliberate v1 simplifications, isolated behind named seams so they can be
changed without reworking the app:
- **Azure-only** provider, no model picker (other providers were dropped for v1).
- **1-to-1** mapping (the data model and slot wiring leave room for 1-to-many).
- **No persistence** of runs beyond the files on disk and the last mapping mirrored
  in `localStorage`; the in-memory job runner (`core/jobs.py`) can be swapped for a
  real queue later.
- **Entity-type filtering** is captured at the API/runner boundary
  (`run_mapping(entity_types=...)`) but row-level filtering is left as a TODO until
  each framework's entity-tier column is documented.
