from fastapi import APIRouter

from backend.app.api.routes import (
    analyses,
    analyze,
    exports,
    health,
    moments,
    scenes,
    transcript,
    uploads,
)

api_router = APIRouter()
api_router.include_router(analyses.router)
api_router.include_router(analyze.router)
api_router.include_router(exports.router)
api_router.include_router(health.router)
api_router.include_router(moments.router)
api_router.include_router(scenes.router)
api_router.include_router(transcript.router)
api_router.include_router(uploads.router)
