from datetime import UTC, datetime

import pytest

from app.core.config import Settings
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
from app.research.source_integrity import canonicalize_url, deduplicate_sources, score_claims


def research_result(agent, url):
    source = SearchSource(
        title="Source",
        url=url,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    claim = Claim(statement="Revenue grew", evidence="Reported growth", source_urls=[source.url])
    return ResearchResult(
        agent=agent,
        strategy="test",
        status=AgentStatus.SUCCEEDED,
        claims=[claim],
        sources=[source],
    )


def cluster(results):
    references = [
        ClaimReference(
            agent=result.agent,
            statement=result.claims[0].statement,
            evidence=result.claims[0].evidence,
            source_urls=result.claims[0].source_urls,
        )
        for result in results
    ]
    return ClaimCluster(
        cluster_id="cluster_1",
        topic="Revenue",
        summary="Revenue grew",
        claims=references,
        supporting_agents=[result.agent for result in results],
        agent_agreement=len(results),
    )


def test_url_canonicalization_strips_tracking_and_normalizes_host():
    canonical, domain = canonicalize_url("HTTPS://Example.COM/report?utm_source=x&b=2&a=1#section")
    assert canonical == "https://example.com/report?a=1&b=2"
    assert domain == "example.com"


def test_duplicate_domain_is_one_source_identity():
    results = [
        research_result(AgentName.BROAD, "https://Reuters.com/a?utm_source=x"),
        research_result(AgentName.ACADEMIC, "https://reuters.com/b"),
        research_result(AgentName.RECENT, "https://REUTERS.COM/c"),
    ]
    records = deduplicate_sources(results)
    assert len(records) == 1
    assert records[0].source_identity == "reuters.com"
    assert records[0].citing_agents == list(AgentName)


def test_duplicate_sources_reduce_independence_despite_agent_agreement():
    results = [
        research_result(agent, f"https://same.example/article-{index}")
        for index, agent in enumerate(AgentName)
    ]
    score = score_claims(
        [cluster(results)],
        results,
        [],
        Settings(_env_file=None),
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )["cluster_1"]
    assert score.agreement_score == 1.0
    assert score.independence_score == 0.3333


def test_contradiction_penalty_is_transparent_and_changes_score():
    results = [
        research_result(AgentName.BROAD, "https://agency.gov/a"),
        research_result(AgentName.ACADEMIC, "https://university.edu/b"),
        research_result(AgentName.RECENT, "https://journal.org/c"),
    ]
    claim_cluster = cluster(results)
    position = ContradictionPosition(
        statement="Revenue grew",
        supporting_agents=[AgentName.BROAD],
        evidence=["Evidence"],
        source_urls=["https://agency.gov/a"],
    )
    contradiction = Contradiction(
        cluster_id="cluster_1",
        disputed_claim="Revenue",
        positions=[position, position.model_copy(update={"statement": "Revenue fell"})],
    )
    settings = Settings(_env_file=None)
    without = score_claims([claim_cluster], results, [], settings)["cluster_1"]
    with_conflict = score_claims([claim_cluster], results, [contradiction], settings)["cluster_1"]
    assert without.final_score - with_conflict.final_score == pytest.approx(0.1)
    assert with_conflict.contradiction_penalty == 1.0
