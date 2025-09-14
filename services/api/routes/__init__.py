from fastapi import APIRouter
from .jobs import router as jobs_router
from .artifacts import router as artifacts_router
from .logs import router as logs_router
from .progress import router as progress_router

router = APIRouter(prefix="/v1")

@router.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "dream-forge", "version": "v1"}

router.include_router(jobs_router)
router.include_router(artifacts_router)
router.include_router(logs_router)
router.include_router(progress_router)
