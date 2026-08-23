from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.jobs import JobRecord
from app.api.models import ResearchHistoryItem, ResearchReport
from app.db.models import (
    AgentRunRow,
    Base,
    ClaimClusterRow,
    ClaimRow,
    ContradictionRow,
    FinalReportRow,
    ResearchSessionRow,
    UserRow,
)
from app.research.state import ResearchState


class DatabaseJobStore:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def upsert_user(self, user_id: str, email: str, name: str, picture: str | None) -> None:
        async with self._sessions.begin() as session:
            user = await session.get(UserRow, user_id)
            if user is None:
                session.add(UserRow(id=user_id, email=email, name=name, picture=picture))
            else:
                user.email = email
                user.name = name
                user.picture = picture

    async def create(self, job_id: str, user_id: str, query: str) -> JobRecord:
        created_at = datetime.now(UTC)
        async with self._sessions.begin() as session:
            if await session.get(UserRow, user_id) is None:
                session.add(
                    UserRow(
                        id=user_id,
                        email=f"{user_id}@local.invalid",
                        name=user_id,
                    )
                )
            session.add(
                ResearchSessionRow(
                    id=job_id,
                    user_id=user_id,
                    query=query,
                    status="running",
                    created_at=created_at,
                )
            )
        return JobRecord(
            job_id=job_id,
            user_id=user_id,
            query=query,
            status="running",
            created_at=created_at,
        )

    async def get_for_user(self, job_id: str, user_id: str) -> JobRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ResearchSessionRow).where(
                    ResearchSessionRow.id == job_id,
                    ResearchSessionRow.user_id == user_id,
                )
            )
            if row is None:
                return None
            report_row = await session.scalar(
                select(FinalReportRow).where(FinalReportRow.session_id == job_id)
            )
            return JobRecord(
                job_id=row.id,
                user_id=row.user_id,
                query=row.query,
                status=row.status,  # type: ignore[arg-type]
                created_at=row.created_at,
                completed_at=row.completed_at,
                report=ResearchReport.model_validate(report_row.report) if report_row else None,
                error=row.error,
                cache_hit=row.cache_hit,
            )

    async def complete(self, job_id: str, state: ResearchState, *, cache_hit: bool = False) -> None:
        completed_at = datetime.now(UTC)
        async with self._sessions.begin() as session:
            research = await session.get(ResearchSessionRow, job_id)
            if research is None:
                raise KeyError(f"Unknown research job {job_id}")
            research.completed_at = completed_at
            if state["status"] == "failed":
                research.status = "failed"
                research.error = "Research pipeline failed"
                return

            research.status = "completed"
            research.cache_hit = cache_hit
            report = ResearchReport(
                job_id=job_id,
                query=research.query,
                agent_results=state["agent_results"],
                claim_clusters=state.get("claim_clusters", []),
                contradictions=state.get("contradictions", []),
                contested_points=state.get("contested_points", []),
                deduplicated_sources=state.get("deduplicated_sources", []),
                confidence_scores=state.get("confidence_scores", {}),
                final_answer=state.get("final_answer", ""),
                cache_hit=cache_hit,
            )
            self._add_research_rows(session, job_id, report)

    @staticmethod
    def _add_research_rows(session, job_id: str, report: ResearchReport) -> None:
        for result in report.agent_results:
            session.add(
                AgentRunRow(
                    session_id=job_id,
                    agent_name=result.agent.value,
                    strategy=result.strategy,
                    status=result.status.value,
                    output=result.model_dump(mode="json"),
                )
            )
        cluster_by_claim = {
            (reference.agent, reference.statement): cluster.cluster_id
            for cluster in report.claim_clusters
            for reference in cluster.claims
        }
        for result in report.agent_results:
            for claim in result.claims:
                session.add(
                    ClaimRow(
                        session_id=job_id,
                        cluster_id=cluster_by_claim.get((result.agent, claim.statement)),
                        agent_name=result.agent.value,
                        statement=claim.statement,
                        evidence=claim.evidence,
                        source_urls=[str(url) for url in claim.source_urls],
                    )
                )
        for cluster in report.claim_clusters:
            session.add(
                ClaimClusterRow(
                    session_id=job_id,
                    cluster_id=cluster.cluster_id,
                    topic=cluster.topic,
                    summary=cluster.summary,
                    data=cluster.model_dump(mode="json"),
                )
            )
        for contradiction in report.contradictions:
            session.add(
                ContradictionRow(
                    session_id=job_id,
                    cluster_id=contradiction.cluster_id,
                    disputed_claim=contradiction.disputed_claim,
                    data=contradiction.model_dump(mode="json"),
                )
            )
        session.add(
            FinalReportRow(
                session_id=job_id,
                final_answer=report.final_answer,
                contested_points=[item.model_dump(mode="json") for item in report.contested_points],
                report=report.model_dump(mode="json"),
            )
        )

    async def fail(self, job_id: str, error: str) -> None:
        async with self._sessions.begin() as session:
            research = await session.get(ResearchSessionRow, job_id)
            if research is None:
                raise KeyError(f"Unknown research job {job_id}")
            research.status = "failed"
            research.error = error
            research.completed_at = datetime.now(UTC)

    async def history_for_user(self, user_id: str) -> list[ResearchHistoryItem]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ResearchSessionRow)
                    .where(ResearchSessionRow.user_id == user_id)
                    .order_by(ResearchSessionRow.created_at.desc())
                )
            ).all()
        return [
            ResearchHistoryItem(
                job_id=row.id,
                query=row.query,
                status=row.status,  # type: ignore[arg-type]
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]
