# NIS2 Mapper — Web application

A **React + TypeScript** SPA on a **FastAPI** backend, wrapping the existing mapping
pipeline (`src/`). Ships as a single Docker image.

## Architecture

```
webapp/
  core/            # UI-agnostic business logic (reuses src/ unchanged)
    catalog.py        # framework registry (add a country = add an entry)
    config_builder.py # UI selection + Azure creds -> load_config(overrides=...)
    settings_state.py # AzureCreds + connection test (Azure-only in v1)
    categories.py     # ENISA categories for the baseline domain selector
    jobs.py           # in-memory background job runner (swap for a queue later)
    pipeline_runner.py# orchestrates the mapping (mirrors run_agent.main)
    baseline_runner.py# consolidation filtered by selected categories
    pdf_report.py     # executive-summary PDF
  api/             # FastAPI REST layer
    main.py           # app + CORS (dev) + serves the built SPA
    deps.py           # Azure creds from request headers
    routes/           # frameworks, categories, settings, mappings, baselines
  frontend/        # React + Vite + TypeScript + Tailwind v4 SPA
    src/pages/        # NewMapping, Baseline
    src/components/    # Sidebar, Header, SettingsModal, FrameworkCard
    src/api/client.ts # typed fetch wrapper
  main.py          # `python -m webapp.main` -> uvicorn
```

The pipeline in `src/` is reused unchanged except one additive hook:
`load_config(overrides=...)` injects Azure credentials + the selected frameworks
without writing to `.env`.

## Run with Docker (recommended)

```bash
docker build -t nis2-mapper .
docker run -p 8080:8080 nis2-mapper
```

Open http://localhost:8080. The build strips the API key from `.env` in a discarded
stage, so **no secret is baked into the image**. Optionally persist the framework
cache and outputs across runs:

```bash
docker run -p 8080:8080 -v nis2_cache:/app/docs/cache -v nis2_out:/app/output nis2-mapper
```

## Run locally (dev)

Backend:
```bash
python -m pip install -r requirements.txt
python -m webapp.main           # FastAPI on :8080 (serves built SPA if present)
```

Frontend (hot reload, proxies /api to :8080):
```bash
cd webapp/frontend
npm install
npm run dev                     # Vite on :5173
```

For a production-style local run, `npm run build` then just `python -m webapp.main`
(FastAPI serves `webapp/frontend/dist`).

## Settings

Open **Paramètres** (gear, top-right): Azure endpoint + API key (+ version), then
**Tester la connexion** / **Enregistrer**. The key is stored **only in the browser**
(localStorage) and sent to the backend as a request header per call — never persisted
on the server.

## Flow

1. **Nouveau Mapping** — pick Source + Target, *Lancer l'analyse*, download **Excel**
   (full) or **PDF** (executive summary).
2. **Baseline Groupe** — after a mapping, tick the ENISA categories to include and
   build the consolidated compliance control list (Excel download).