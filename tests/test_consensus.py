from app.research.agents import AgentDependencies
from app.research.consensus import ConsensusAnalyzer, cluster_exact_claims
from app.research.graph import run_research_agents
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


def result(agent: AgentName, statement: str) -> ResearchResult:
    url = f"https://{agent.value}.example/report"
    return ResearchResult(
        agent=agent,
        strategy="test",
        status=AgentStatus.SUCCEEDED,
        claims=[
            Claim(
                statement=statement,
                evidence=f"Evidence for {statement}",
                source_urls=[url],
            )
        ],
        sources=[SearchSource(title="Report", url=url)],
    )


def test_exact_comparison_clusters_all_agent_agreement():
    clusters = cluster_exact_claims([result(agent, "Revenue grew 10%.") for agent in AgentName])
    assert len(clusters) == 1
    assert clusters[0].agent_agreement == 3
    assert clusters[0].supporting_agents == list(AgentName)


def test_exact_comparison_keeps_partial_disagreement_visible():
    clusters = cluster_exact_claims(
        [
            result(AgentName.BROAD, "Revenue grew 10%."),
            result(AgentName.ACADEMIC, "Revenue grew 10%"),
            result(AgentName.RECENT, "Revenue fell 5%."),
        ]
    )
    assert len(clusters) == 2
    assert sorted(cluster.agent_agreement for cluster in clusters) == [1, 2]


def test_contradiction_validation_uses_original_evidence_and_sources():
    references = [
        ClaimReference(
            agent=AgentName.BROAD,
            statement="Revenue grew",
            evidence="Filing reports growth",
            source_urls=["https://company.example/filing"],
        ),
        ClaimReference(
            agent=AgentName.RECENT,
            statement="Revenue fell",
            evidence="Results report a decline",
            source_urls=["https://news.example/results"],
        ),
    ]
    cluster = ClaimCluster(
        cluster_id="cluster_1",
        topic="Revenue direction",
        summary="Sources disagree on revenue direction",
        claims=references,
        supporting_agents=[AgentName.BROAD, AgentName.RECENT],
        agent_agreement=2,
    )
    proposed = Contradiction(
        cluster_id="cluster_1",
        disputed_claim="Revenue direction",
        positions=[
            ContradictionPosition(
                statement=reference.statement,
                supporting_agents=[AgentName.ACADEMIC],
                evidence=["invented evidence"],
                source_urls=["https://invented.example"],
            )
            for reference in references
        ],
    )

    validated = ConsensusAnalyzer._validate_contradictions([proposed], [cluster])

    assert validated[0].positions[0].evidence == ["Filing reports growth"]
    assert str(validated[0].positions[0].source_urls[0]) == "https://company.example/filing"
    assert validated[0].positions[0].supporting_agents == [AgentName.BROAD]


async def test_graph_preserves_resolved_contradiction_positions():
    async def search(request):
        return [SearchSource(title="Report", url="https://example.com/report")]

    async def extract(query, agent, strategy, sources):
        statement = "Treatment helps" if agent != AgentName.RECENT else "Treatment does not help"
        return [Claim(statement=statement, evidence=statement, source_urls=[sources[0].url])]

    async def compare(query, results):
        references = [
            ClaimReference(
                agent=result.agent,
                statement=claim.statement,
                evidence=claim.evidence,
                source_urls=claim.source_urls,
            )
            for result in results
            for claim in result.claims
        ]
        return [
            ClaimCluster(
                cluster_id="cluster_1",
                topic="Treatment effectiveness",
                summary="Sources disagree about treatment effectiveness",
                claims=references,
                supporting_agents=list(AgentName),
                agent_agreement=3,
            )
        ]

    async def resolve(query, clusters):
        claims = [reference for cluster in clusters for reference in cluster.claims]
        return [
            Contradiction(
                cluster_id=clusters[0].cluster_id,
                disputed_claim="Whether treatment helps",
                positions=[
                    ContradictionPosition(
                        statement=claim.statement,
                        supporting_agents=[claim.agent],
                        evidence=[claim.evidence],
                        source_urls=claim.source_urls,
                    )
                    for claim in (claims[0], claims[-1])
                ],
            )
        ]

    dependencies = AgentDependencies(
        search=search,
        extract=extract,
        timeout_seconds=1,
        recent_news_days=30,
        compare=compare,
        resolve=resolve,
    )
    state = await run_research_agents("Does treatment help?", "user", dependencies=dependencies)

    assert len(state["contradictions"]) == 1
    assert state["contested_points"] == state["contradictions"]
    assert len(state["contradictions"][0].positions) == 2
    assert state["status"] == "completed"
    assert "Contested points" in state["final_answer"]


async def test_consensus_failure_marks_graph_failed_without_erasing_agent_results():
    async def search(request):
        return [SearchSource(title="Report", url="https://example.com/report")]

    async def extract(query, agent, strategy, sources):
        return [Claim(statement="Claim", evidence="Evidence", source_urls=[sources[0].url])]

    async def malformed_compare(query, results):
        raise ValueError("malformed structured output")

    dependencies = AgentDependencies(
        search=search,
        extract=extract,
        timeout_seconds=1,
        recent_news_days=30,
        compare=malformed_compare,
    )
    state = await run_research_agents("Question", "user", dependencies=dependencies)

    assert state["status"] == "failed"
    assert len(state["agent_results"]) == 3
    assert state["claim_clusters"] == []


async def test_empty_evidence_synthesizes_explicit_insufficiency_message():
    async def search(request):
        return []

    async def extract(query, agent, strategy, sources):
        return []

    dependencies = AgentDependencies(
        search=search,
        extract=extract,
        timeout_seconds=1,
        recent_news_days=30,
    )
    state = await run_research_agents("Unknown question", "user", dependencies=dependencies)

    assert state["status"] == "completed"
    assert "insufficient" in state["final_answer"].lower()
