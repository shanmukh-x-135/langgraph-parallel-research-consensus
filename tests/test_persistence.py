from sqlalchemy import func, select

from app.db.models import (
    AgentRunRow,
    ClaimClusterRow,
    ClaimRow,
    ContradictionRow,
    FinalReportRow,
    ResearchSessionRow,
    UserRow,
)
from app.db.store import DatabaseJobStore
from app.research.models import (
    AgentName,
    AgentStatus,
    Claim,
    ClaimCluster,
    ClaimReference,
    Contradiction,
    ContradictionPosition,
    ResearchResult,
    SearchSource,
)


def completed_state(job_id: str):
    source = SearchSource(title="Filing", url="https://company.example/filing")
    claim = Claim(
        statement="Revenue grew 10%",
        evidence="The filing reports ten percent growth",
        source_urls=[source.url],
    )
    reference = ClaimReference(
        agent=AgentName.BROAD,
        statement=claim.statement,
        evidence=claim.evidence,
        source_urls=claim.source_urls,
    )
    cluster = ClaimCluster(
        cluster_id="cluster_1",
        topic="Revenue growth",
        summary=claim.statement,
        claims=[reference],
        supporting_agents=[AgentName.BROAD],
        agent_agreement=1,
    )
    contradiction = Contradiction(
        cluster_id="cluster_1",
        disputed_claim="Revenue growth",
        positions=[
            ContradictionPosition(
                statement="Revenue grew 10%",
                supporting_agents=[AgentName.BROAD],
                evidence=[claim.evidence],
                source_urls=[source.url],
            ),
            ContradictionPosition(
                statement="Revenue did not grow",
                supporting_agents=[AgentName.RECENT],
                evidence=["A later report disputes growth"],
                source_urls=["https://news.example/report"],
            ),
        ],
    )
    return {
        "job_id": job_id,
        "user_id": "user-1",
        "query": "Did revenue grow?",
        "agent_results": [
            ResearchResult(
                agent=AgentName.BROAD,
                strategy="broad",
                status=AgentStatus.SUCCEEDED,
                claims=[claim],
                sources=[source],
            ),
            ResearchResult(
                agent=AgentName.ACADEMIC,
                strategy="academic",
                status=AgentStatus.SUCCEEDED,
            ),
            ResearchResult(
                agent=AgentName.RECENT,
                strategy="recent",
                status=AgentStatus.SUCCEEDED,
            ),
        ],
        "claim_clusters": [cluster],
        "contradictions": [contradiction],
        "contested_points": [contradiction],
        "final_answer": "Revenue grew according to the filing, but a later report disputes it.",
        "status": "running",
    }


async def test_completed_research_survives_store_restart(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'research.db'}"
    first_store = DatabaseJobStore(database_url)
    await first_store.initialize()
    await first_store.upsert_user("user-1", "user@example.com", "User One", None)
    await first_store.create("job-1", "user-1", "Did revenue grow?")
    await first_store.complete("job-1", completed_state("job-1"), cache_hit=True)
    await first_store.dispose()

    restarted_store = DatabaseJobStore(database_url)
    await restarted_store.initialize()
    record = await restarted_store.get_for_user("job-1", "user-1")
    assert record is not None
    assert record.status == "completed"
    assert record.report is not None
    assert record.report.final_answer.startswith("Revenue grew")
    assert record.cache_hit is True
    assert record.report.cache_hit is True
    assert len(record.report.agent_results) == 3
    assert len(record.report.contradictions) == 1
    assert await restarted_store.get_for_user("job-1", "user-2") is None
    history = await restarted_store.history_for_user("user-1")
    assert [item.job_id for item in history] == ["job-1"]
    await restarted_store.dispose()


async def test_all_prd_tables_receive_completed_research_rows(tmp_path):
    store = DatabaseJobStore(f"sqlite+aiosqlite:///{tmp_path / 'tables.db'}")
    await store.initialize()
    await store.upsert_user("user-1", "user@example.com", "User One", None)
    await store.create("job-1", "user-1", "Did revenue grow?")
    await store.complete("job-1", completed_state("job-1"))

    expected_counts = {
        UserRow: 1,
        ResearchSessionRow: 1,
        AgentRunRow: 3,
        ClaimRow: 1,
        ClaimClusterRow: 1,
        ContradictionRow: 1,
        FinalReportRow: 1,
    }
    async with store._sessions() as session:
        for model, expected in expected_counts.items():
            count = await session.scalar(select(func.count()).select_from(model))
            assert count == expected
    await store.dispose()
