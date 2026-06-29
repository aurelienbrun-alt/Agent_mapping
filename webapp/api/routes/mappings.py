from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from webapp.api.deps import get_creds
from webapp.api.schemas import JobOut, MappingStartIn, StartOut
from webapp.core import jobs
from webapp.core.catalog import get_framework
from webapp.core.config_builder import build_config
from webapp.core.pipeline_runner import run_mapping
from webapp.core.pdf_report import generate_mapping_pdf
from webapp.core.settings_state import AzureCreds

router = APIRouter(tags=["mappings"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/mappings", response_model=StartOut)
def start_mapping(body: MappingStartIn, creds: AzureCreds = Depends(get_creds)) -> StartOut:
    if not creds.is_set:
        raise HTTPException(status_code=400, detail="Clé API Azure manquante. Configurez-la dans les paramètres.")
    try:
        source = get_framework(body.source_id)
        target = get_framework(body.target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    cfg = build_config(source, target, creds)
    job = jobs.submit("mapping", run_mapping, cfg, entity_types=body.entity_types)
    return StartOut(job_id=job.id)


@router.get("/mappings/{job_id}", response_model=JobOut)
def mapping_status(job_id: str) -> JobOut:
    job = jobs.get(job_id)
    if job is None or job.kind != "mapping":
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    result = None
    if job.status == "done" and job.result is not None:
        r = job.result
        result = {
            "run_id": r.run_id,
            "source_name": r.source_name,
            "target_name": r.target_name,
            "summary": r.summary,
        }
    return JobOut(id=job.id, kind=job.kind, status=job.status, stage=job.stage, error=job.error, result=result)


@router.get("/mappings/{job_id}/download")
def mapping_download(job_id: str, fmt: str = "excel"):
    job = jobs.get(job_id)
    if job is None or job.kind != "mapping" or job.status != "done" or job.result is None:
        raise HTTPException(status_code=404, detail="Résultat indisponible.")
    r = job.result
    if fmt == "pdf":
        pdf = generate_mapping_pdf(
            source_name=r.source_name, target_name=r.target_name, run_id=r.run_id,
            summary=r.summary, a_to_b=r.a_to_b, out_dir=r.output_path.parent,
        )
        return FileResponse(pdf, filename=pdf.name, media_type="application/pdf")
    return FileResponse(r.output_path, filename=r.output_path.name, media_type=_XLSX)
