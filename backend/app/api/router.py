from fastapi import APIRouter

from backend.app.api.routes import analyze, health, scenes, uploads

api_router = APIRouter()
api_router.include_router(analyze.router)
api_router.include_router(health.router)
api_router.include_router(scenes.router)
api_router.include_router(uploads.router)
