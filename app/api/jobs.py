import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.api.models import JobStatus, ResearchHistoryItem, ResearchReport
from app.research.state import ResearchState

ResearchRunner = Callable[..., Awaitable[ResearchState]]


@dataclass
class JobRecord:
    job_id: str
    user_id: str
    query: str
    status: JobStatus
    created_at: datetime
    completed_at: datetime | None = None
    report: ResearchReport | None = None
    error: str | None = None


class InMemoryJobStore:
    """Milestone 3 registry; PostgreSQL replaces it in Milestone 5."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, job_id: str, user_id: str, query: str) -> JobRecord:
        record = JobRecord(
            job_id=job_id,
            user_id=user_id,
            query=query,
            status="running",
            created_at=datetime.now(UTC),
        )
        async with self._lock:
            self._jobs[job_id] = record
        return record

    async def get_for_user(self, job_id: str, user_id: str) -> JobRecord | None:
        async with self._lock:
            record = self._jobs.get(job_id)
            return record if record and record.user_id == user_id else None

    async def complete(self, job_id: str, state: ResearchState) -> None:
        async with self._lock:
            record = self._jobs[job_id]
            record.completed_at = datetime.now(UTC)
            if state["status"] == "failed":
                record.status = "failed"
                record.error = "Research pipeline failed"
                return
            record.status = "completed"
            record.report = ResearchReport(
                job_id=job_id,
                query=record.query,
                agent_results=state["agent_results"],
                claim_clusters=state.get("claim_clusters", []),
                contradictions=state.get("contradictions", []),
                contested_points=state.get("contested_points", []),
                final_answer=state.get("final_answer", ""),
            )

    async def fail(self, job_id: str, error: str) -> None:
        async with self._lock:
            record = self._jobs[job_id]
            record.status = "failed"
            record.error = error
            record.completed_at = datetime.now(UTC)

    async def history_for_user(self, user_id: str) -> list[ResearchHistoryItem]:
        async with self._lock:
            records = [record for record in self._jobs.values() if record.user_id == user_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return [
            ResearchHistoryItem(
                job_id=record.job_id,
                query=record.query,
                status=record.status,
                created_at=record.created_at,
                completed_at=record.completed_at,
            )
            for record in records
        ]


async def execute_research_job(
    store: InMemoryJobStore,
    runner: ResearchRunner,
    job_id: str,
    user_id: str,
    query: str,
) -> None:
    try:
        state = await runner(query, user_id, job_id=job_id)
        await store.complete(job_id, state)
    except Exception as exc:
        await store.fail(job_id, f"{type(exc).__name__}: {exc}")
