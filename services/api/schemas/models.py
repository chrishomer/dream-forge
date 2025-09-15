from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSummary(BaseModel):
    id: str
    name: str
    kind: str
    version: str | None = None
    installed: bool = False
    enabled: bool = True
    parameters_schema: dict = Field(default_factory=dict)


class ModelDescriptor(ModelSummary):
    capabilities: list[str] = Field(default_factory=lambda: ["generate"])  # constant for M3
    source_uri: str | None = None
    local_path: str | None = None
    files_json: list[dict] = Field(default_factory=list)


class ModelListResponse(BaseModel):
    models: list[ModelSummary] = Field(default_factory=list)

