# FinFeed architecture

## Current target structure

The project is a modular monolith. Domain packages own business rules and data
contracts; adapters own framework and provider details. Dependencies point
inward: transport/UI -> application/domain -> storage and external adapters.

```text
finfeed/
  core/                 ingestion orchestration and parser contracts
  application/          framework-independent use-case services (NewsService, MarketService)
  storage/              SQLite models, repositories and exporters
  market/               market-data domain (service, store, collectors)
  screener/             screening domain (factors, scoring, reports)
  ecal/                 economic-calendar domain
  llm/                  AI-analysis domain
  integrations/         optional provider adapters and their FastAPI routers
  ui/
    web_fastapi/        HTTP composition root only
      core/             API error contract and cross-cutting transport policy
      routers/          transport boundaries; business goes to application/
    web/
      shared.py         shared runtime: SSE channel, API cache, source names,
                        news response builder, web state (single instances)
      server.py         legacy stdlib HTTP service (fallback only)
web/src/
  shared/               framework-neutral browser utilities and configuration
  features/             feature-owned API adapters, state and components
  ui/                   reusable primitive components and design tokens
  views/                route-level composition only
```

## Rules

1. A feature imports its own API adapter, never Axios or environment variables.
2. `shared/` contains no financial business rules and must not import features.
3. Domain packages do not import FastAPI, Vue, or UI packages. HTTP modules only
   validate input, call a service, and map output to a response.
4. New FastAPI routes raise `ApiError` for expected failures. The application
   boundary serializes a single `{ success, error: { code, message, details } }`
   contract; legacy endpoints may be migrated incrementally.
5. Database SQL remains in `storage/` or a domain `store.py`; views, routers,
   and collectors do not embed it.

## Migration plan

The initial refactor establishes the shared API client, feature-owned adapters,
runtime configuration, and server error boundary without changing public URLs.
Compatibility facades remain under `web/src/api/` so existing imports continue
to work. New code must use `@/shared/*` or its owning `@/features/<name>/*`.
The Python dependency source of truth is `pyproject.toml`; `requirements.txt`
is retained only as a compatibility pointer to that canonical manifest.

`routers/realtime.py` owns SSE, SSE health, and market WebSocket routes. It
receives a `NewsEventPublisher` dependency backed by the shared broadcaster
(`ui/web/shared.py`), which is the single instance shared with the legacy
service. Market use cases live in `application/market_service.py`
(`MarketService`); news use cases live in `application/news_service.py`
(`NewsService`). Routers depend on these service facades, not on
`ui/web/server.py` globals — the legacy module now only owns its HTTP handler
and `start/stop_web_server` lifecycle control.
