"""List, download and visualize the mapping workbooks in the output directory."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from webapp.core import output_browser

router = APIRouter(tags=["outputs"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/outputs")
def list_outputs() -> list[dict]:
    return output_browser.list_outputs()


@router.get("/outputs/{name}/view")
def view_output(name: str) -> dict:
    try:
        return output_browser.parse_workbook(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the UI
        raise HTTPException(status_code=400, detail=f"Lecture du classeur impossible : {exc}") from None


@router.get("/outputs/{name}/download")
def download_output(name: str):
    try:
        path = output_browser.safe_output_path(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return FileResponse(path, filename=path.name, media_type=_XLSX)
