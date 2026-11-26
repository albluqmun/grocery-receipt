# E6: Flutter App - Basic Screens (Search + Price History)

## Summary

First frontend epic: a Flutter web app with two screens — product search and price history.
Also includes backend changes: API key auth, search endpoint, price history endpoint, and CORS.

## Scope

### In scope
- API key middleware for backend protection
- Product search query param (`?q=`) on existing endpoint
- Price history endpoint (`GET /api/v1/products/:id/prices`)
- CORS configuration
- Flutter web app with 2 screens: search + product detail
- Run on Chrome (Flutter web)

### Out of scope
- Login/registration (single user, API key is sufficient)
- Charts/graphs (deferred to E7)
- Flutter tests (deferred to when app has more substance)
- Mobile/desktop builds (Chrome only for now)

## Backend Changes

### 1. API Key Middleware

- New env var `API_KEY` in `.env`
- FastAPI middleware validates `X-API-Key` header on all routes except `GET /health`
- Missing or invalid key returns `401 Unauthorized`
- Swagger UI configured with `APIKeyHeader` security scheme (lock icon in UI)

### 2. Product Search

Extend `GET /api/v1/products` with optional query param `q`:
- When present, filters products where `name` OR `off_name` contains the text
- Case-insensitive partial match (`ILIKE '%text%'`)
- Compatible with existing `skip`/`limit` pagination
- When absent, behaves as before (returns all products paginated)

### 3. Price History Endpoint

`GET /api/v1/products/{product_id}/prices`

Returns the purchase history for a product, derived from line_items joined with tickets and supermarkets.

Response schema `PriceHistoryEntry`:
```
{
  "date": "2026-03-15",
  "supermarket_name": "MERCADONA",
  "unit_price": 1.85
}
```

Response: `list[PriceHistoryEntry]` ordered by date descending.

Returns `404` if product does not exist. Returns empty list if product has no purchases.

### 4. CORS

- Add `CORSMiddleware` to FastAPI app
- Allowed origins configurable via env var `CORS_ORIGINS` (comma-separated)
- Default in dev: `http://localhost:*` patterns

## Frontend Architecture

### Tech Stack
- **Flutter** (web target, Chrome)
- **Riverpod** — state management
- **Dio** — HTTP client with interceptors
- **go_router** — declarative navigation

### Project Structure

```
frontend/
├── lib/
│   ├── main.dart                  # Entry point, providers, router
│   ├── config/
│   │   └── api_config.dart        # Base URL, API key from dart-define
│   ├── models/
│   │   └── product.dart           # DTOs: Product, PriceHistoryEntry
│   ├── services/
│   │   └── api_service.dart       # Dio client, API key interceptor
│   ├── providers/
│   │   ├── product_search.dart    # Search provider with debounce
│   │   └── price_history.dart     # Price history for a product
│   ├── screens/
│   │   ├── search_screen.dart     # Main screen: search bar + results list
│   │   └── product_screen.dart    # Detail: image + price table
│   └── widgets/
│       ├── search_bar.dart        # TextField with ~300ms debounce
│       ├── product_tile.dart      # List item in search results
│       └── price_table.dart       # Table: date | supermarket | price
├── pubspec.yaml
└── web/
```

### Navigation (go_router)

| Route | Screen | Description |
|-------|--------|-------------|
| `/` | `SearchScreen` | Main screen with search bar and results |
| `/product/:id` | `ProductScreen` | Product detail with image and price table |

### Data Flow

**Search flow:**
1. User types in `SearchBar`
2. ~300ms debounce
3. Riverpod provider calls `GET /api/v1/products?q=text&limit=20`
4. Results shown as `ProductTile` list (name, brand, off_name if different)
5. Tap a product → navigate to `/product/:id`

**Detail flow:**
1. Provider calls `GET /api/v1/products/:id` for product data
2. Provider calls `GET /api/v1/products/:id/prices` for price history
3. Show `off_image_url` image (or placeholder if absent)
4. Show `PriceTable`: date | supermarket | unit_price

### Configuration

- API key and base URL via `--dart-define` at build time:
  `flutter run -d chrome --dart-define=API_KEY=xxx --dart-define=API_BASE_URL=http://localhost:8000`
- Dev defaults: `localhost:8000`
- Dio interceptor adds `X-API-Key` header to all requests

## Testing (Backend Only)

### API Key Middleware
- Request without key → 401
- Request with wrong key → 401
- Request with correct key → passes through
- `GET /health` without key → 200

### Product Search (`?q=`)
- Search by `name` match
- Search by `off_name` match
- Case-insensitive match
- No results → empty list with total=0
- Combined with pagination (skip/limit)

### Price History
- Product with purchases → list of entries ordered by date desc
- Product without purchases → empty list
- Non-existent product → 404
