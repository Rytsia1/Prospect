# ADR-006: API as a Vercel Service Next to the Web App

## Status

Accepted. Supersedes ADR-005 for the API only; the worker, database and storage decisions of
ADR-005 stand.

## Context

ADR-005 ran the FastAPI API on Railway or Render and had the Next.js app proxy `/api/v1` to it
(`middleware.ts`, `API_ORIGIN`), passing the visitor's IP with a shared `TRUSTED_PROXY_SECRET`.
That is two platforms, two domains and a proxy hop for every API call. Vercel can deploy several
services from one repository as one project, with shared routing and one domain.

## Decision

One Vercel project, configured by `vercel.json` at the repository root:

| Service | Root | Public path |
|---|---|---|
| `web` | `apps/web` (Next.js) | `/(.*)`, everything else |
| `api` | `apps/api` (FastAPI, entrypoint `app/main.py`) | `/api/(.*)`; its routes are under `/api/v1` |

- The browser still talks to one origin, so the session cookie stays first-party
  (`__Host-`, HttpOnly, SameSite=Strict) and the API needs no credentialed CORS.
- Vercel's edge routes `/api/*` to the API before the web app sees it, so on Vercel the web
  app neither proxies nor needs `API_ORIGIN` or `TRUSTED_PROXY_SECRET`. Outside Vercel (or with
  the API elsewhere) `API_ORIGIN` keeps the ADR-005 proxy working unchanged.
- No service calls another from server code, so there are no service bindings.
- The worker is not a Vercel service: PDF parsing is long-running and needs the process sandbox
  (ADR-003, docs/SECURITY_P2_5.md). It stays on Railway or Render.

Consequences in code (all keyed on `VERCEL=1`, which the platform sets):

- **Client IP for rate limits** (`app/ratelimit.py`): taken from `X-Real-IP`, which Vercel's
  edge sets to the connecting client; any other request keeps ADR-005's rule (only the proxy
  secret may name an IP, else the TCP peer).
- **Startup** (`app/config.py`): `TRUSTED_PROXY_SECRET` is not required in production.
- **Database** (`app/db.py`): no connection pool and no server-side prepared statements, because
  function instances are short-lived and `DATABASE_URL` must be an external transaction pooler.

## Consequences

- One domain, one deployment, no proxy hop.
- Function limits apply to the API: request and response bodies of at most 4.5 MB (PDFs go
  straight from the browser to storage, but very large exports could hit it) and a maximum
  duration per request.
- `/health` is not public (only `/api/*` is routed to the API); use deployment status and logs.
- Project environment variables are visible to both services; the web app reads only
  `STORAGE_ORIGIN`.
- Migrations run from the deploy step as the database owner, not from a start command.
