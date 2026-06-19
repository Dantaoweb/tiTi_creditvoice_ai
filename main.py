import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app_routes import register_http_routes
from database import Base, engine
from schema_updates import ensure_schema_updates
from web_routes import register_web_routes
from webhook_routes import register_webhook_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    from proactive_scheduler import run_proactive_scheduler
    task = asyncio.create_task(run_proactive_scheduler())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

Base.metadata.create_all(engine)
ensure_schema_updates(engine)

register_http_routes(app)
register_web_routes(app)
register_webhook_routes(app)


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/app/", status_code=302)
