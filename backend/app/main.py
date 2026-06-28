import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Prepare local runtime directories when the application starts."""
    settings = get_settings()
    for directory in settings.runtime_directories:
        directory.mkdir(parents=True, exist_ok=True)
    logger.info("MomentAI API started in %s mode", settings.environment)
    yield
    logger.info("MomentAI API stopped")


def create_application() -> FastAPI:
    """Create and configure the MomentAI API application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version="0.4.1",
        description="MomentAI Milestone 4B transcript foundation API.",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    application.mount(
        "/thumbnails",
        StaticFiles(directory=settings.thumbnail_dir, check_dir=False),
        name="thumbnails",
    )
    return application


app = create_application()
