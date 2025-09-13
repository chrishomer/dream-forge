from fastapi import APIRouter

router = APIRouter(prefix="/v1")

@router.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "dream-forge", "version": "v1"}

