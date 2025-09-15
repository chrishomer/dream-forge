from __future__ import annotations

from fastapi import APIRouter, HTTPException

from modules.persistence.db import get_session
from modules.persistence import repos
from services.api.schemas.models import ModelDescriptor, ModelListResponse, ModelSummary


router = APIRouter(prefix="", tags=["models"])


@router.get("/models", response_model=ModelListResponse)
def list_models() -> ModelListResponse:
    # Lean surface: returns installed+enabled models only
    with get_session() as session:
        rows = repos.list_models(session, enabled_only=True)
    models = [
        ModelSummary(
            id=str(m.id),
            name=m.name,
            kind=m.kind,
            version=m.version,
            installed=bool(m.installed),
            enabled=bool(m.enabled),
            parameters_schema=m.parameters_schema or {},
        )
        for m in rows
    ]
    return ModelListResponse(models=models)


@router.get("/models/{model_id}", response_model=ModelDescriptor)
def get_model(model_id: str) -> ModelDescriptor:
    with get_session() as session:
        m = repos.get_model(session, model_id)
        if not m:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "model not found"})
    return ModelDescriptor(
        id=str(m.id),
        name=m.name,
        kind=m.kind,
        version=m.version,
        installed=bool(m.installed),
        enabled=bool(m.enabled),
        parameters_schema=m.parameters_schema or {},
        capabilities=m.capabilities or ["generate"],
        source_uri=m.source_uri,
        local_path=m.local_path,
        files_json=m.files_json or [],
    )

