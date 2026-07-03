# syntax=docker/dockerfile:1
#
# Single-image build for the NIS2 Mapper (React SPA + FastAPI + pipeline).
# Build:  docker build -t nis2-mapper .
# Run:    docker run -p 8080:8080 nis2-mapper   ->  http://localhost:8080
#
# The Azure API key is entered in the app (stored in the browser) and sent per
# request, so it is NOT baked into the image: only .env.example (a sanitized
# template with an empty AZURE_OPENAI_API_KEY) is committed and shipped. The real
# .env with secrets is git-ignored and never enters the build context.

# ---- Stage 1: build the React SPA ----
FROM node:20-alpine AS frontend
WORKDIR /app
COPY webapp/frontend/package.json ./
RUN npm install
COPY webapp/frontend/ ./
RUN npm run build
# -> /app/dist

# ---- Stage 2: Python runtime ----
FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEBAPP_HOST=0.0.0.0 \
    WEBAPP_PORT=8080

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY src/ ./src/
COPY webapp/__init__.py webapp/main.py ./webapp/
COPY webapp/core/ ./webapp/core/
COPY webapp/api/ ./webapp/api/
# Data / config / templates (not secret)
COPY data/ ./data/
COPY config/ ./config/
COPY templates/ ./templates/
# Sanitized .env template (prompts + deployments, no API key) and the built SPA.
# The API key is supplied at runtime (entered in the app UI), not baked here.
COPY .env.example ./.env
COPY --from=frontend /app/dist ./webapp/frontend/dist

# Writable runtime dirs (mount volumes here to persist cache/output across runs)
RUN mkdir -p docs/cache logs output reports

EXPOSE 8080
CMD ["uvicorn", "webapp.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
