import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.research.models import (
    AgentName,
    AgentStatus,
    Claim,
    ClaimCluster,
    Contradiction,
    ResearchResult,
    SearchSource,
)
from app.research.search import SearchRequest
from app.research.state import ResearchState

SearchFunction = Callable[[SearchRequest], Awaitable[list[SearchSource]]]
ExtractFunction = Callable[
    [str, AgentName, str, list[SearchSource]],
    Awaitable[list[Claim]],
]
CompareFunction = Callable[[str, list[ResearchResult]], Awaitable[list[ClaimCluster]]]
ResolveFunction = Callable[[str, list[ClaimCluster]], Awaitable[list[Contradiction]]]


@dataclass(frozen=True)
class AgentDependencies:
    search: SearchFunction
    extract: ExtractFunction
    timeout_seconds: float
    recent_news_days: int
    compare: CompareFunction | None = None
    resolve: ResolveFunction | None = None


ACADEMIC_DOMAINS = [
    "arxiv.org",
    "jstor.org",
    "nature.com",
    "ncbi.nlm.nih.gov",
    "science.org",
    "ssrn.com",
]


async def _run_agent(
    state: ResearchState,
    dependencies: AgentDependencies,
    *,
    agent: AgentName,
    strategy: str,
    request: SearchRequest,
) -> dict[str, list[ResearchResult]]:
    async def research() -> ResearchResult:
        sources = await dependencies.search(request)
        claims = await dependencies.extract(state["query"], agent, strategy, sources)
        return ResearchResult(
            agent=agent,
            strategy=strategy,
            status=AgentStatus.SUCCEEDED,
            claims=claims,
            sources=sources,
        )

    try:
        result = await asyncio.wait_for(research(), timeout=dependencies.timeout_seconds)
    except TimeoutError:
        result = ResearchResult(
            agent=agent,
            strategy=strategy,
            status=AgentStatus.TIMED_OUT,
            error=f"Agent exceeded {dependencies.timeout_seconds:g}s timeout",
        )
    except Exception as exc:  # External search/LLM failures are isolated to this branch.
        result = ResearchResult(
            agent=agent,
            strategy=strategy,
            status=AgentStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
    return {"agent_results": [result]}


def create_agent_nodes(dependencies: AgentDependencies) -> dict[str, Callable]:
    async def agent_broad(state: ResearchState) -> dict[str, list[ResearchResult]]:
        return await _run_agent(
            state,
            dependencies,
            agent=AgentName.BROAD,
            strategy="Wide general-web search using Tavily advanced search.",
            request=SearchRequest(query=state["query"], search_depth="advanced"),
        )

    async def agent_academic(state: ResearchState) -> dict[str, list[ResearchResult]]:
        return await _run_agent(
            state,
            dependencies,
            agent=AgentName.ACADEMIC,
            strategy="Scholarly search restricted to established academic domains.",
            request=SearchRequest(
                query=f"{state['query']} peer reviewed research study",
                search_depth="advanced",
                include_domains=ACADEMIC_DOMAINS,
            ),
        )

    async def agent_recent(state: ResearchState) -> dict[str, list[ResearchResult]]:
        return await _run_agent(
            state,
            dependencies,
            agent=AgentName.RECENT,
            strategy="Recent-news search limited to a configurable time window.",
            request=SearchRequest(
                query=state["query"],
                topic="news",
                search_depth="advanced",
                days=dependencies.recent_news_days,
            ),
        )

    return {
        "agent_broad": agent_broad,
        "agent_academic": agent_academic,
        "agent_recent": agent_recent,
    }
