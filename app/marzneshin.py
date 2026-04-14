import logging
import mimetypes
from contextlib import asynccontextmanager
from typing import AsyncGenerator

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi_pagination import add_pagination
from starlette.staticfiles import StaticFiles
from uvicorn import Config, Server

from app.core.settings import settings
from app.core.middleware import TimeoutMiddleware
from app.core.exceptions import validation_exception_handler
from app.core.scheduler import create_scheduler
from app.templates import render_template
from . import __version__
from .routes import api_router
from .tasks import nodes_startup
from .webhooks import webhooks_router

logger = logging.getLogger(__name__)

scheduler = create_scheduler()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await nodes_startup()
    yield
    scheduler.shutdown()


def create_app() -> FastAPI:
    application = FastAPI(
        title="MarzneshinAPI",
        description="Unified GUI Censorship Resistant Solution Powered by Xray",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs else None,
        redoc_url="/redoc" if settings.docs else None,
    )

    application.webhooks.include_router(webhooks_router)
    application.include_router(api_router)
    add_pagination(application)

    @application.get("/", response_class=HTMLResponse)
    def home_page():
        return render_template(settings.home_page_template)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        TimeoutMiddleware, timeout=settings.request_timeout
    )

    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )

    return application


app = create_app()


async def main():
    if not settings.debug:
        app.mount(
            settings.dashboard_path,
            StaticFiles(directory="dashboard/dist", html=True),
            name="dashboard",
        )
        app.mount(
            "/static/",
            StaticFiles(directory="dashboard/dist/static"),
            name="static",
        )
        app.mount(
            "/locales/",
            StaticFiles(directory="dashboard/dist/locales"),
            name="locales",
        )

    scheduler.start()

    cfg = Config(
        app=app,
        host=settings.uvicorn.host,
        port=settings.uvicorn.port,
        uds=(None if settings.debug else settings.uvicorn.uds),
        ssl_certfile=settings.uvicorn.ssl_certfile,
        ssl_keyfile=settings.uvicorn.ssl_keyfile,
        workers=1,
        reload=settings.debug,
        log_level=logging.DEBUG if settings.debug else logging.INFO,
        timeout_keep_alive=settings.uvicorn.timeout_keep_alive,
    )
    server = Server(cfg)
    await server.serve()
