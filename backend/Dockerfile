FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set INSTALL_DEV=true to include test/lint tooling (used by docker-compose only)
ARG INSTALL_DEV=false

COPY pyproject.toml ./
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir ".[dev]"; \
    else pip install --no-cache-dir .; fi

RUN useradd --system --uid 1000 --no-create-home app

COPY --chown=app:app . .

USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
