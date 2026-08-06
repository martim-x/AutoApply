# Playwright Python image already includes Chromium + OS libs.
# Tag must match playwright package version from poetry.lock.
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    ENABLE_REMOTE_BROWSER=true \
    DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/rabota_apply.sqlite \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    POETRY_VERSION=2.1.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PORT=8080

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root \
    && playwright install --with-deps chromium

COPY . .
RUN poetry install --only main \
    && mkdir -p /app/data /app/data/sessions /app/data/reports

EXPOSE 8080

# Railway injects PORT; default 8080 for local compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
