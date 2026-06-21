import asyncio
import logging
import os
import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app_routes import register_http_routes
from database import Base, engine
from schema_updates import ensure_schema_updates
from web_routes import register_web_routes
from webhook_routes import register_webhook_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Sentry error tracking — initialises only when SENTRY_DSN is set in environment
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
    except ImportError:
        logging.warning("SENTRY_DSN set but sentry-sdk not installed — pip install sentry-sdk")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # SCHEDULER_ENABLED guards against duplicate notifications when multiple
    # workers or instances are running. render.yaml sets it on exactly one
    # process; unset means disabled (safe default for multi-worker setups).
    task = None
    if os.getenv("SCHEDULER_ENABLED", "false").lower() == "true":
        from proactive_scheduler import run_proactive_scheduler
        task = asyncio.create_task(run_proactive_scheduler())
    yield
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


_dev = os.getenv("ENVIRONMENT", "production") == "development"
app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if _dev else None,
    redoc_url="/redoc" if _dev else None,
    openapi_url="/openapi.json" if _dev else None,
)

Base.metadata.create_all(engine)
ensure_schema_updates(engine)

# ── Trusted host validation ───────────────────────────────────────────────────
# Rejects requests whose Host header isn't in the allowlist, blocking
# Host header injection attacks. Wildcards allowed (e.g. *.onrender.com).
_allowed_hosts = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# ── Global request body size limit ───────────────────────────────────────────
# Caps JSON API requests at 4 MB (voice endpoint uses its own Pydantic
# max_length of 2 M chars ≈ 1.5 MB binary). Rejects before the body is
# read so a single oversized upload can't tie up the worker.
_MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(4 * 1024 * 1024)))  # 4 MB


class _MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > _MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "Request body too large."},
            )
        return await call_next(request)


app.add_middleware(_MaxBodySizeMiddleware)

# ── Request timing middleware ─────────────────────────────────────────────────
# Logs every API request with method, path, status code, and wall-clock
# duration in milliseconds. Static asset requests are skipped to avoid
# flooding the log stream with noise.
_APP_START = time.monotonic()
_timing_log = logging.getLogger("creditvoice.timing")


class _RequestTimingMiddleware(BaseHTTPMiddleware):
    _SKIP_PREFIXES = ("/app/assets/", "/web/static/", "/favicon")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)
        t0 = time.monotonic()
        response = await call_next(request)
        ms = (time.monotonic() - t0) * 1000
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400 or ms > 3000:
            level = logging.WARNING
        else:
            level = logging.INFO
        _timing_log.log(
            level,
            "%s %s %s %.0fms",
            request.method,
            path,
            response.status_code,
            ms,
        )
        return response


app.add_middleware(_RequestTimingMiddleware)

# ── Explicit CORS policy — driven by env var so it's auditable and intentional.
# Production: set CORS_ALLOWED_ORIGINS to your Render URL (no trailing slash).
# Development: Vite proxies /app/api to localhost:8000 so the browser sees
# same-origin requests — leave blank or set to http://localhost:5173.
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

register_http_routes(app)
register_web_routes(app)
register_webhook_routes(app)

_log = logging.getLogger("creditvoice")

# ── Production credential check ───────────────────────────────────────────────
# Warn loudly at boot when critical third-party secrets are absent so the
# operator notices immediately rather than discovering the gap via an incident.
_REQUIRED_PRODUCTION_VARS = [
    ("META_APP_SECRET",      "WhatsApp webhooks will reject all incoming messages"),
    ("MONNIFY_API_KEY",      "Monnify payment initiation will fail"),
    ("MONNIFY_SECRET_KEY",   "Monnify payment webhooks will be rejected"),
    ("OPENAI_API_KEY",       "AI parsing and voice transcription will be disabled"),
    ("WEB_SECRET_KEY",       "Session tokens are insecure — using default dev key"),
    ("WHATSAPP_TOKEN",       "Outbound WhatsApp messages cannot be sent"),
    ("PHONE_NUMBER_ID",      "Outbound WhatsApp messages cannot be sent"),
]

if not _dev:
    _missing = [(v, msg) for v, msg in _REQUIRED_PRODUCTION_VARS if not os.getenv(v)]
    for _var, _impact in _missing:
        _log.critical("MISSING ENV VAR: %s — %s", _var, _impact)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    _log.error(
        "Unhandled exception: %s %s\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again."},
    )


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/app/", status_code=302)
