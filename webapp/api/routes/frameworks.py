from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from webapp.core import catalog
from webapp.core.catalog import FrameworkEntry
from webapp.core.framework_import import add_custom_framework
from webapp.api.schemas import FrameworkOut

router = APIRouter(tags=["frameworks"])


def _to_out(f: FrameworkEntry) -> FrameworkOut:
    return FrameworkOut(
        id=f.id,
        display_name=f.display_name,
        country=f.country,
        requirement_count=f.requirement_count,
        description=f.description,
        available=f.available,
        custom=f.custom,
    )


@router.get("/frameworks", response_model=list[FrameworkOut])
def get_frameworks() -> list[FrameworkOut]:
    return [_to_out(f) for f in catalog.list_frameworks()]


@router.post("/frameworks/import", response_model=FrameworkOut)
async def import_framework(
    file: UploadFile = File(...),
    display_name: str = Form(...),
    country: str = Form(""),
) -> FrameworkOut:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Format non supporté : fournissez un fichier .xlsx.")
    try:
        entry = add_custom_framework(raw=raw, display_name=display_name, country=country)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _to_out(entry)


@router.delete("/frameworks/{framework_id}")
def delete_framework(framework_id: str) -> dict[str, str]:
    try:
        entry = catalog.get_framework(framework_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Framework introuvable.") from None
    if not entry.custom:
        raise HTTPException(status_code=400, detail="Les frameworks intégrés ne peuvent pas être supprimés.")
    catalog.remove_custom_framework(framework_id)
    return {"deleted": framework_id}
