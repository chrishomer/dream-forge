from __future__ import annotations

from pydantic import BaseModel, Field


class ArtifactOut(BaseModel):
    id: str
    format: str
    width: int
    height: int
    seed: int | None = None
    item_index: int
    s3_key: str
    url: str
    expires_at: str


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactOut] = Field(default_factory=list)

