# Multi-stage image: cache Poetry deps separately from app source.
# Playwright tag must match poetry.lock (playwright==1.62.0).
# Use -noble (Python 3.12); -jammy ships 3.10 and fails requires-python >=3.11.

# ----- deps: install Python packages + ensure Chromium -----
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble AS deps

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    POETRY_VERSION=2.1.3 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_OPTIONS_NO_PIP=false

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Cache-friendly: lockfile layer invalidates only when dependencies change.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root \
    && /app/.venv/bin/playwright install --with-deps chromium

# ----- runtime: venv + app resources from build context -----
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    ENABLE_REMOTE_BROWSER=true \
    DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/auto_apply_app.sqlite \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /app/.venv /app/.venv
# Browsers may already exist in the base image; copy deps-stage install for consistency.
COPY --from=deps /ms-playwright /ms-playwright

# Application (no .env / data — excluded via .dockerignore; secrets via compose mounts).
COPY app ./app
COPY letters ./letters
COPY letter_universal.txt ./letter_universal.txt
COPY pyproject.toml poetry.lock ./
COPY config/areas.json config/weights.json \
     config/launch.example.json config/linkedin.launch.example.json \
     ./config/

RUN mkdir -p /app/data /app/data/sessions /app/data/reports

EXPOSE 8080

# Railway injects PORT; default 8080 for local compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
