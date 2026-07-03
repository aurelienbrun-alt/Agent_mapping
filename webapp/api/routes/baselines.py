from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from webapp.api.schemas import BaselineStartIn, JobOut, StartOut
from webapp.core import jobs
from webapp.core.baseline_runner import build_baseline

router = APIRouter(tags=["baselines"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/baselines", response_model=StartOut)
def start_baseline(body: BaselineStartIn) -> StartOut:
    mapping_job = jobs.get(body.mapping_job_id)
    if mapping_job is None or mapping_job.kind != "mapping" or mapping_job.status != "done" or mapping_job.result is None:
        raise HTTPException(status_code=400, detail="No mapping available. Run an analysis first.")
    if not body.categories:
        raise HTTPException(status_code=400, detail="Select at least one ENISA category.")
    job = jobs.submit("baseline", build_baseline, mapping_job.result, body.categories)
    return StartOut(job_id=job.id)


@router.get("/baselines/{job_id}", response_model=JobOut)
def baseline_status(job_id: str) -> JobOut:
    job = jobs.get(job_id)
    if job is None or job.kind != "baseline":
        raise HTTPException(status_code=404, detail="Baseline not found.")
    result = None
    if job.status == "done" and job.result is not None:
        result = {"summary": job.result.summary, "selected_categories": job.result.selected_categories}
    return JobOut(id=job.id, kind=job.kind, status=job.status, stage=job.stage, error=job.error, result=result)


@router.get("/baselines/{job_id}/download")
def baseline_download(job_id: str):
    job = jobs.get(job_id)
    if job is None or job.kind != "baseline" or job.status != "done" or job.result is None:
        raise HTTPException(status_code=404, detail="Result unavailable.")
    path = job.result.output_path
    return FileResponse(path, filename=path.name, media_type=_XLSX)
