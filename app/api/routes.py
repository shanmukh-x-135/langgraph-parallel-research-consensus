from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.auth import get_current_user_id
from app.api.jobs import InMemoryJobStore, ResearchRunner, execute_research_job
from app.api.models import (
    ResearchHistoryItem,
    ResearchReport,
    ResearchRequest,
    ResearchStartResponse,
    ResearchStatusResponse,
)

router = APIRouter()
CurrentUser = Annotated[str, Depends(get_current_user_id)]


def _services(request: Request) -> tuple[InMemoryJobStore, ResearchRunner]:
    return request.app.state.job_store, request.app.state.research_runner


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/research", response_model=ResearchStartResponse, status_code=status.HTTP_202_ACCEPTED
)
async def start_research(
    payload: ResearchRequest,
    background_tasks: BackgroundTasks,
    user_id: CurrentUser,
    request: Request,
) -> ResearchStartResponse:
    store, runner = _services(request)
    job_id = str(uuid4())
    await store.create(job_id, user_id, payload.query)
    background_tasks.add_task(execute_research_job, store, runner, job_id, user_id, payload.query)
    return ResearchStartResponse(job_id=job_id, status="running")


@router.get("/research/{job_id}/status", response_model=ResearchStatusResponse)
async def research_status(
    job_id: str, user_id: CurrentUser, request: Request
) -> ResearchStatusResponse:
    store, _ = _services(request)
    record = await store.get_for_user(job_id, user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    return ResearchStatusResponse(job_id=job_id, status=record.status, error=record.error)


@router.get("/research/history", response_model=list[ResearchHistoryItem])
async def research_history(user_id: CurrentUser, request: Request) -> list[ResearchHistoryItem]:
    store, _ = _services(request)
    return await store.history_for_user(user_id)


@router.get("/research/{job_id}", response_model=ResearchReport)
async def research_result(job_id: str, user_id: CurrentUser, request: Request) -> ResearchReport:
    store, _ = _services(request)
    record = await store.get_for_user(job_id, user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research job not found")
    if record.status != "completed" or record.report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Research job is {record.status}",
        )
    return record.report
