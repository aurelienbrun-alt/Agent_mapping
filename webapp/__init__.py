"""Web application for the NIS2 regulatory framework mapper.

Layout:
- webapp/core/  : UI-agnostic business logic (catalog, config injection, jobs,
                  pipeline + baseline runners). Reuses src/ unchanged. This layer
                  has no NiceGUI/Frontend dependency, so the presentation layer is
                  a swappable seam (NiceGUI today, REST + React possible later).
- webapp/ui/    : NiceGUI presentation layer (thin).
- webapp/main.py: entry point (`python -m webapp.main`).
"""
