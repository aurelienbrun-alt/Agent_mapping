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

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from webapp.api.routes import frameworks, categories, settings, mappings, baselines, outputs

logger = logging.getLogger("webapp")

_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bring-your-own-key guardrail.

    Each user supplies their own Azure key from the browser; it is sent per request
    and never persisted server-side. A key sitting in the server environment would
    become a *shared* fallback that anyone reaching the API could spend against, so
    surface it loudly at startup instead of using it silently. Deployed environments
    must leave it empty (the shipped `.env.example` template has it blank).
    """
    load_dotenv(_ROOT / ".env")
    if os.getenv("AZURE_OPENAI_API_KEY", "").strip():
        logger.warning(
            "AZURE_OPENAI_API_KEY is set in the server environment. The web app expects "
            "each user to bring their own key from the UI; a server-side key acts as a "
            "shared, billable fallback. Leave it empty in any deployed environment."
        )
    yield


app = FastAPI(title="Compliance Assistant API", version="1.0.0", lifespan=lifespan)

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
_DIST = (Path(__file__).resolve().parents[1] / "frontend" / "dist").resolve()


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
    if full_path:
        candidate = (_DIST / full_path).resolve()
        # Contain within the built-assets dir: a crafted path (…/../) must never
        # escape dist/ and read arbitrary files. Anything else falls back to the SPA.
        if (candidate == _DIST or _DIST in candidate.parents) and candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(_DIST / "index.html")
