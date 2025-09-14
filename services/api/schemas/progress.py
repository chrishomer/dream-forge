from __future__ import annotations

from pydantic import BaseModel


class ProgressItem(BaseModel):
    item_index: int
    progress: float


class ProgressResponse(BaseModel):
    progress: float
    items: list[ProgressItem] = []
    stages: list[dict] = []

