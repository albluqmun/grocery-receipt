# Grocery Receipt — Flutter Web Client

Frontend para el tracker de precios de supermercado. Web only (Chrome).

## Requisitos

- Flutter SDK 3.5+
- Backend corriendo en `http://localhost:8000` (ver raíz del repo: `docker compose up`).

## Variables (dart-define)

| Nombre          | Default                   | Descripción                              |
|-----------------|---------------------------|------------------------------------------|
| `API_BASE_URL`  | `http://localhost:8000`   | URL base del backend (sin `/api/v1`).    |
| `API_KEY`       | *(vacío)*                 | Clave enviada en `X-API-Key`.            |

## Dev

```bash
flutter pub get
flutter run -d chrome --web-port=5000 \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=API_KEY=your-dev-key
```

## Build

```bash
flutter build web --release \
  --dart-define=API_BASE_URL=https://api.example.com \
  --dart-define=API_KEY=prod-key
```

El artefacto queda en `build/web/`.
