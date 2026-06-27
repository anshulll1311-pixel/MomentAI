from fastapi import APIRouter

from backend.app.api.routes import health, uploads

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(uploads.router)
