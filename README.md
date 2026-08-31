# CreditVoice / tiTi

A business-management platform for Nigerian SMEs — a WhatsApp assistant (**tiTi**)
plus a web dashboard. Record sales, track customer credit, manage inventory, run
thrift/ajo savings, and more.

> **What & why** the product does → see [`PRD.md`](PRD.md).
> **How to run the code** → this README.

## Stack
- **Backend:** Python 3.11, FastAPI, SQLAlchemy. Entry: `main.py`.
- **Frontend:** React 19 + Vite (`frontend/`), builds to `web/dist/`, served by
  FastAPI at `/app` (base path `/app/`).
- **DB:** SQLite in dev, PostgreSQL in prod. Schema via `Base.metadata.create_all`
  + idempotent `schema_updates.py` (ALTERs) at startup.
- **AI:** Claude (message interpretation), OpenAI Whisper (voice).
- **Channels:** Meta WhatsApp Cloud API; Monnify (payments/wallet).
- **Host:** Render (see `render.yaml`).

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
