from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from webapp.api.deps import get_creds
from webapp.api.schemas import TestConnectionOut
from webapp.core.settings_state import AzureCreds, test_connection

router = APIRouter(tags=["settings"])


@router.post("/settings/test", response_model=TestConnectionOut)
async def test(creds: AzureCreds = Depends(get_creds)) -> TestConnectionOut:
    ok, message = await run_in_threadpool(test_connection, creds)
    return TestConnectionOut(ok=ok, message=message)
