import asyncio
from time import monotonic

import pytest

from app.research.agents import AgentDependencies
from app.research.graph import AGENT_NODE_NAMES, build_research_graph, run_research_agents
from app.research.models import AgentName, AgentStatus, Claim, SearchSource
from app.research.search import SearchRequest


def source(url: str = "https://example.com/report") -> SearchSource:
    return SearchSource(title="Report", url=url, snippet="Evidence")


async def extract_claims(query, agent, strategy, sources):
    if not sources:
        return []
    return [
        Claim(
            statement=f"Claim from {agent}",
            evidence="Evidence",
            source_urls=[sources[0].url],
        )
    ]


def dependencies(search, extract=extract_claims, timeout=0.5):
    return AgentDependencies(
        search=search,
        extract=extract,
        timeout_seconds=timeout,
        recent_news_days=14,
    )


@pytest.mark.asyncio
async def test_three_agents_run_concurrently_with_distinct_strategies():
    requests: list[SearchRequest] = []

    async def search(request):
        requests.append(request)
        await asyncio.sleep(0.08)
        return [source()]

    started = monotonic()
    result = await run_research_agents("test question", "user-1", dependencies=dependencies(search))
    elapsed = monotonic() - started

    assert elapsed < 0.18
    assert [item.agent for item in result["agent_results"]] == list(AgentName)
    assert all(item.status == AgentStatus.SUCCEEDED for item in result["agent_results"])
    assert {request.topic for request in requests} == {"general", "news"}
    assert any(request.include_domains for request in requests)
    assert any(request.days == 14 for request in requests)


@pytest.mark.asyncio
async def test_one_agent_failure_does_not_fail_graph():
    async def search(request):
        if request.include_domains:
            raise RuntimeError("academic provider unavailable")
        return [source()]

    result = await run_research_agents("question", "user-1", dependencies=dependencies(search))
    statuses = {item.agent: item.status for item in result["agent_results"]}

    assert statuses[AgentName.ACADEMIC] == AgentStatus.FAILED
    assert statuses[AgentName.BROAD] == AgentStatus.SUCCEEDED
    assert statuses[AgentName.RECENT] == AgentStatus.SUCCEEDED
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_timeout_is_isolated_to_one_agent():
    async def search(request):
        if request.topic == "news":
            await asyncio.sleep(0.1)
        return [source()]

    result = await run_research_agents(
        "question", "user-1", dependencies=dependencies(search, timeout=0.02)
    )
    statuses = {item.agent: item.status for item in result["agent_results"]}
    assert statuses[AgentName.RECENT] == AgentStatus.TIMED_OUT
    assert sum(status == AgentStatus.SUCCEEDED for status in statuses.values()) == 2


@pytest.mark.asyncio
async def test_empty_search_results_are_valid_empty_agent_output():
    async def search(request):
        return []

    result = await run_research_agents("question", "user-1", dependencies=dependencies(search))
    assert all(item.status == AgentStatus.SUCCEEDED for item in result["agent_results"])
    assert all(not item.claims and not item.sources for item in result["agent_results"])


@pytest.mark.asyncio
async def test_malformed_extraction_is_captured_as_agent_failure():
    async def search(request):
        return [source()]

    async def malformed_extract(query, agent, strategy, sources):
        raise ValueError("structured output validation failed")

    result = await run_research_agents(
        "question", "user-1", dependencies=dependencies(search, malformed_extract)
    )
    assert all(item.status == AgentStatus.FAILED for item in result["agent_results"])
    assert result["status"] == "failed"


def test_graph_has_fixed_three_agent_fan_out_and_fan_in():
    async def search(request):
        return []

    graph = build_research_graph(dependencies(search))
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    for node_name in AGENT_NODE_NAMES:
        assert ("__start__", node_name) in edges
        assert (node_name, "collect_findings") in edges
    assert ("collect_findings", "__end__") in edges
