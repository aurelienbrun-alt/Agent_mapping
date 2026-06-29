"""Pydantic request/response models for the API."""
from __future__ import annotations

from pydantic import BaseModel


class FrameworkOut(BaseModel):
    id: str
    display_name: str
    country: str
    requirement_count: int
    description: str
    available: bool
    custom: bool = False


class CategoryOut(BaseModel):
    name: str
    number: str
    definition: str


class TestConnectionOut(BaseModel):
    ok: bool
    message: str


class MappingStartIn(BaseModel):
    source_id: str
    target_id: str
    entity_types: list[str] = ["essential", "important"]


class BaselineStartIn(BaseModel):
    mapping_job_id: str
    categories: list[str]


class StartOut(BaseModel):
    job_id: str


class JobOut(BaseModel):
    id: str
    kind: str
    status: str            # running | done | error
    stage: str = ""
    error: str = ""
    result: dict | None = None
