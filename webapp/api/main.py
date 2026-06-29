"""FastAPI application: REST API + static SPA hosting.

In production the built React app (webapp/frontend/dist) is served from the same
origin as the API, so no CORS is needed. CORS is enabled only for the Vite dev
server (localhost:5173) during development.
"""
from __future__ import annotations

import sys

# UTF-8 stdout on Windows so pipeline logging (accents / arrows) never crashes a run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from webapp.api.routes import frameworks, categories, settings, mappings, baselines, outputs

app = FastAPI(title="NIS2 Mapper API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (frameworks, categories, settings, mappings, baselines, outputs):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Static SPA (built React app) --------------------------------------------
_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    """Serve built assets, falling back to index.html for client-side routes."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if not _DIST.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend non disponible. En dev, lancez Vite (npm run dev); en prod, buildez l'image Docker.",
        )
    candidate = _DIST / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(_DIST / "index.html")
