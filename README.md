# CreditVoice / tiTi

A business-management platform for Nigerian SMEs — a WhatsApp assistant (**tiTi**)
plus a web dashboard. Record sales, track customer credit, manage inventory, run
thrift/ajo savings, and more.

> **What & why** the product does → see [`PRD.md`](PRD.md).
> **How to run the code** → this README.

## Tech stack

Entry point: `main.py` (FastAPI). The React app builds to `web/dist/` and is
served by FastAPI at `/app`. Versions below are pinned in `requirements.txt` /
`frontend/package.json`.

### Backend
| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 | Runtime |
| FastAPI | 0.136.1 | Web framework / API + webhooks |
| Uvicorn | 0.47.0 | ASGI server |
| Pydantic | 2.13.4 | Request validation / schemas |
| SQLAlchemy | 2.0.49 | ORM (all queries — parameterized) |
| psycopg2-binary | 2.9.12 | PostgreSQL driver (prod) |
| SQLite | stdlib | Dev database |
| requests | 2.34.2 | Outbound HTTP (WhatsApp, Monnify, Claude) |
| python-dotenv | 1.2.2 | Local env loading |
| fpdf2 | 2.8.7 | PDF receipts / statements |

### Frontend
| Tool | Version | Purpose |
|---|---|---|
| React | 19.2.6 | UI (SPA) |
| react-dom | 19.2.6 | DOM renderer |
| react-router-dom | 7.18.1 | Client-side routing (`/app/*`) |
| lucide-react | 1.17.0 | Icons |
| Vite | 8.1.x | Build tool / bundler |
| @vitejs/plugin-react | 6.0.2 | React build support |
| vite-plugin-pwa | 1.3.0 | PWA manifest + service worker (installable / TWA) |
| ESLint | 10.3.0 | Linting |

### AI / ML
| Tool | Purpose |
|---|---|
| Anthropic **Claude** (via HTTP API) | tiTi conversational replies (`ANTHROPIC_API_KEY`) |
| OpenAI (`openai` 2.36.0) | Transaction-parse fallback + **Whisper** voice transcription |

### Integrations & services
| Service | Purpose |
|---|---|
| Meta **WhatsApp Cloud API** (Graph v18) | Send/receive tiTi messages; signed webhooks |
| **Monnify** | Payments / virtual accounts / wallet (HMAC-verified webhooks) |
| **pywebpush** 2.4.0 (VAPID) | Web push notifications |
| **SMTP** | Transactional email (admin/notifications) |
| **Sentry** (`sentry-sdk` 2.63.0) | Error monitoring |

### Infrastructure & tooling
| Tool | Purpose |
|---|---|
| **Render** (`render.yaml`) | Hosting (web service + Postgres) |
| **Cloudflare** | DNS (DNS-only; Render handles TLS/CDN/DDoS) |
| **GitHub Actions** (`.github/workflows/ci.yml`) | CI: pytest, py_compile, secret scan, dependency audit, migration guard, frontend build |
| **pytest** 9.0.3 | Test suite |
| **Google Play (TWA)** | Android packaging via PWA (assetlinks) |

**Data layer:** SQLite in dev, PostgreSQL in prod; schema created by
`Base.metadata.create_all` plus idempotent `schema_updates.py` (ALTERs) at startup.

## Prerequisites
- Python 3.11, Node 20+ (CI uses Node 24), npm.

## Setup & run (local dev)
```bash
# 1. Backend deps
pip install -r requirements.txt

# 2. Frontend build (outputs to web/dist/, which FastAPI serves at /app)
cd frontend && npm install && npm run build && cd ..

# 3. Minimum env for local dev
export DATABASE_URL="sqlite:///./dev.db"
export ENVIRONMENT="development"
export WEB_SECRET_KEY="dev-secret-not-for-prod"

# 4. Run
uvicorn main:app --reload --port 8000
```
Then open:
- `http://localhost:8000/` — landing page
- `http://localhost:8000/app` — the web app (login/dashboard)
- `http://localhost:8000/health` — health check

**Frontend dev loop:** edit under `frontend/src/`, rebuild with
`cd frontend && npm run build`. The built `web/dist/` is committed to git; Render
also rebuilds it on deploy.

## Tests
```bash
pytest -q                 # full suite (mirrors CI)
pytest test_poultry.py -q # a single file
```
CI (`.github/workflows/ci.yml`) runs: pytest, `py_compile`, a secret scan, a
dependency audit (pip-audit + npm prod audit), a destructive-migration guard, and
the frontend build.

## Environment variables
Set real values in the host dashboard (Render → Environment), never in code.
`render.yaml` lists the production keys. Key ones:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres in prod (`sqlite:///…` in dev) |
| `WEB_SECRET_KEY` | **Signs session tokens — MUST be a strong random value in prod** |
| `ENVIRONMENT` | `production` (dev disables Secure cookies) |
| `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID` | Meta Cloud API send |
| `WEBHOOK_VERIFY_TOKEN` | Meta webhook GET verification |
| `META_APP_SECRET` | Verifies inbound webhook signatures (fails closed) |
| `ANTHROPIC_API_KEY` | tiTi LLM replies |
| `OPENAI_API_KEY` | voice transcription / parse fallback |
| `MONNIFY_API_KEY`, `MONNIFY_SECRET_KEY`, `MONNIFY_CONTRACT_CODE`, `MONNIFY_BASE_URL` | wallet / payments |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | web push |
| `SCHEDULER_ENABLED` | background reminders/nudges |
| `TWA_PACKAGE_NAME`, `TWA_SHA256_FINGERPRINT` | Play Store TWA (assetlinks) |

## Deploy (Render)
`render.yaml` defines it:
- **build:** `pip install -r requirements.txt && cd frontend && npm install && npm run build`
- **start:** `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
- **health:** `/health`

Nothing is live until a redeploy + hard refresh. Set all secrets in the dashboard.

## Layout
```
main.py                  FastAPI app, middleware, landing, robots/sitemap
web_*.py                 web API routes (auth, pos, inventory, customers, …)
webhook_*.py             WhatsApp webhook + message routing
*_commands.py            WhatsApp command/flow handlers
models.py                SQLAlchemy models
schema_updates.py        idempotent migrations (ALTERs) run at startup
inventory_suppliers.py   stock movements, matching, supplier logic
poultry.py, thrift_groups.py, wallet_service.py, ...  domain modules
frontend/                React SPA (src/pages, src/components) → web/dist
test_*.py                pytest suite
PRD.md, WHATSAPP_GO_LIVE.md, PLAYSTORE_GO_LIVE.md   product/launch docs
```

## Conventions
- Commit the built `web/dist/` with frontend changes.
- Migrations: **add** columns via `schema_updates.py`; never `DROP` (CI blocks it).
- Every web route scopes data by the session's business (owner) — keep tenant
  isolation intact.
