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

# Reset BD (borrar volumen y recrear tablas al arrancar)
docker compose down -v && docker compose up --build

# Generar migración incremental
docker compose exec api python -m alembic revision --autogenerate -m "description"
```

> **Schema management:** Alembic es la fuente de verdad del schema.
> El lifespan ejecuta `alembic upgrade head` al arrancar, aplicando migraciones pendientes.
> Para cambios de schema: generar migración con `--autogenerate`, o en dev
> `docker compose down -v` y reiniciar para recrear desde cero.

## Quality

- Pre-commit hooks (ruff check + ruff format) vía poetry en la raíz del repo
- CI con GitHub Actions en cada PR: lint + tests con PostgreSQL real
- Instalar hooks: `poetry install && poetry run pre-commit install`

## Conventions

- Idioma: español para strings de usuario (HTTPException detail), inglés para todo lo demás (código, logs, docstrings, comentarios)
- Python 3.12+, async en todo el backend
- Ruff para linting y formateo (line-length=100)
- Config vía variables de entorno (pydantic-settings)
- Conventional commits: `feat:`, `fix:`, `chore:`, etc.
- Ramas con prefijo: `feat/`, `fix/`, `chore/`

## Code Patterns

### Models (`app/models/{entity}.py`)

- Un modelo por fichero, hereda de `UUIDPrimaryKeyMixin, TimestampMixin, Base`
- SQLAlchemy 2.0 con `Mapped` type hints, tabla en plural snake_case
- Relaciones con `lazy="selectin"` y `back_populates`
- Decimales: `Numeric(10, 2)` para dinero, `Numeric(10, 3)` para cantidades

### Schemas (`app/schemas/{entity}.py`)

- Tres schemas por entidad: `{Entity}Create`, `{Entity}Update`, `{Entity}Read`
- Update: todos los campos opcionales con `Field(default=None)`
- Read: incluye `model_config = ConfigDict(from_attributes=True)`
- Paginación genérica: `PaginatedResponse[T]` (en `schemas/pagination.py`)

### Services (`app/services/{entity}.py`)

- Funciones libres async (no clases): `create`, `get_by_id`, `get_list`, `update`, `delete`
- `get_list` retorna `tuple[list[Entity], int]` (items + total)
- Usan `db.flush()` (nunca `db.commit()`, eso lo hace `get_db()`)
- Update usa `data.model_dump(exclude_unset=True)` para parciales
- Retornan `None`/`False` si no existe; el router decide el HTTP status

### Routers (`app/api/{entities}.py`)

- Fichero en plural, importa servicio como `from app.services import entity as entity_service`
- REST: POST(201), GET(200), PATCH(200), DELETE(204)
- Paginación via `Query(skip)` + `Query(limit)` con `PaginatedResponse`
- Errores: helpers `not_found()` y `conflict()` de `app.api.exceptions`
- `IntegrityError` se captura en el router y lanza `conflict()`
- DB inyectada con `Depends(get_db)`

### Tests (`tests/test_{entities}.py`)

- Tests de integración con BD real (nunca mocks para la BD)
- Fixtures en `conftest.py`: `engine`, `db_session`, `client` (con override de `get_db`)
- Helper `_create_{entity}(db, **kwargs)` por fichero para datos de test
- Cubrir: create, create duplicado/conflict, list, get, get 404, update, update 404, delete, delete 404, delete con dependencias (409)
