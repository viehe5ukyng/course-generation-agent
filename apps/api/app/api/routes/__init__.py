from fastapi import APIRouter

from app.api.routes.events import router as events_router
from app.api.routes.experiments import router as experiments_router
from app.api.routes.files import router as files_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.threads import router as threads_router


router = APIRouter(prefix="/api/v1")
router.include_router(threads_router)
router.include_router(files_router)
router.include_router(reviews_router)
router.include_router(events_router)
router.include_router(experiments_router)
