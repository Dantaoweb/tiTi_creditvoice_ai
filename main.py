import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

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

# Explicit CORS policy — driven by env var so it's auditable and intentional.
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
