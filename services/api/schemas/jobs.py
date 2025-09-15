from __future__ import annotations

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    type: str = Field(pattern=r"^generate$")
    prompt: str
    negative_prompt: str | None = None
    width: int = 1024
    height: int = 1024
    steps: int = 30
    guidance: float = 7.0
    scheduler: str | None = None
    format: str = "png"  # png|jpg
    embed_metadata: bool = True
    seed: int | None = None
    # batch 'count' arrives in M4; here we hardcode 1
    model_id: str | None = None


class JobCreated(BaseModel):
    id: str
    status: str
    type: str
    created_at: str


class JobCreatedResponse(BaseModel):
    job: JobCreated


class StepSummary(BaseModel):
    name: str
    status: str


class JobStatusResponse(BaseModel):
    id: str
    type: str
    status: str
    created_at: str
    updated_at: str
    steps: list[StepSummary] = []
    summary: dict = {}
    error_code: str | None = None
    error_message: str | None = None


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict | None = None
    correlation_id: str | None = None
