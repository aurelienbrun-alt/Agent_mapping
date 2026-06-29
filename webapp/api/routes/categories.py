from __future__ import annotations

from fastapi import APIRouter

from webapp.core.categories import list_enisa_categories
from webapp.api.schemas import CategoryOut

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=list[CategoryOut])
def get_categories() -> list[CategoryOut]:
    return [CategoryOut(name=c.name, number=c.number, definition=c.definition) for c in list_enisa_categories()]
