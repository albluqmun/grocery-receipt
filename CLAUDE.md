# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

App para seguimiento de precios de artículos de supermercado, extrayendo datos de tickets PDF de compras previas almacenados en Google Drive.

## Architecture

Monorepo: `backend/` (FastAPI + PostgreSQL) y `frontend/` (Flutter, futuro).

Backend sigue patrón service layer:
- `api/` — FastAPI routers (capa HTTP)
- `services/` — Lógica de negocio
- `models/` — SQLAlchemy ORM models (heredan de `app.core.database.Base`)
- `schemas/` — Pydantic request/response schemas
- `core/` — Configuración (`pydantic-settings`), database, seguridad

## Commands

```bash
# Levantar entorno local
cp .env.example .env
docker compose up --build          # API en :8000, swagger en :8000/swagger

# Con pgAdmin
docker compose --profile debug up  # pgAdmin en :5050

# Tests
docker compose exec api pytest
docker compose exec api pytest tests/test_health.py -v  # test individual

# Lint y formato
docker compose exec api ruff check app/
docker compose exec api ruff format app/

# Migraciones
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head
```

## Conventions

- Idioma: español para strings de usuario, inglés para código
- Python 3.12+, async en todo el backend
- Ruff para linting y formateo (line-length=100)
- Config vía variables de entorno (pydantic-settings)
