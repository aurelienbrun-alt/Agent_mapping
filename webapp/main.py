"""Entry point: `python -m webapp.main` (runs the FastAPI app via uvicorn).

In Docker the CMD calls uvicorn directly; this launcher is for local dev parity.
"""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "webapp.api.main:app",
        host=os.getenv("WEBAPP_HOST", "0.0.0.0"),
        port=int(os.getenv("WEBAPP_PORT", "8080")),
        reload=False,
    )


if __name__ == "__main__":
    main()
