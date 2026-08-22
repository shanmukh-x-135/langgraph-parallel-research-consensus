from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.auth import GoogleIdentity, get_current_user_id
from app.api.jobs import JobStore, ResearchRunner, execute_research_job
from app.api.models import (
    AuthenticatedUser,
    AuthResponse,
    GoogleLoginRequest,
    ResearchHistoryItem,
    ResearchReport,
    ResearchRequest,
    ResearchStartResponse,
    ResearchStatusResponse,
)

router = APIRouter()
CurrentUser = Annotated[str, Depends(get_current_user_id)]


def _services(request: Request) -> tuple[JobStore, ResearchRunner]:
    return request.app.state.job_store, request.app.state.research_runner


@router.post("/auth/google", response_model=AuthResponse)
async def google_login(payload: GoogleLoginRequest, request: Request) -> AuthResponse:
    try:
        identity: GoogleIdentity = await request.app.state.google_verifier(
            payload.id_token, request.app.state.settings
        )
        await request.app.state.job_store.upsert_user(
            identity.id, identity.email, identity.name, identity.picture
        )
        access_token = request.app.state.session_tokens.issue(identity)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return AuthResponse(
        access_token=access_token,
        expires_in=request.app.state.session_tokens.ttl_seconds,
        user=AuthenticatedUser(**identity.model_dump()),
    )


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
    if not await request.app.state.cache_rate_limiter.allow_research(user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Research rate limit exceeded",
        )
    job_id = str(uuid4())
    await store.create(job_id, user_id, payload.query)
    background_tasks.add_task(
        execute_research_job,
        store,
        request.app.state.cache_rate_limiter,
        runner,
        job_id,
        user_id,
        payload.query,
    )
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
