from functools import lru_cache
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings, get_settings
from app.research.agents import AgentDependencies, create_agent_nodes
from app.research.extraction import ClaimExtractor
from app.research.models import AgentStatus
from app.research.search import TavilySearch
from app.research.state import ResearchState

AGENT_NODE_NAMES = ("agent_broad", "agent_academic", "agent_recent")


def collect_findings(state: ResearchState) -> dict[str, Any]:
    """Close Milestone 1's fan-in; consensus nodes are added in Milestone 2."""
    any_succeeded = any(result.status == AgentStatus.SUCCEEDED for result in state["agent_results"])
    return {"status": "running" if any_succeeded else "failed"}


def build_research_graph(dependencies: AgentDependencies):
    builder = StateGraph(ResearchState)
    for node_name, node in create_agent_nodes(dependencies).items():
        builder.add_node(node_name, node)
        builder.add_edge(START, node_name)
        builder.add_edge(node_name, "collect_findings")
    builder.add_node("collect_findings", collect_findings)
    builder.add_edge("collect_findings", END)
    return builder.compile()


def build_default_dependencies(settings: Settings | None = None) -> AgentDependencies:
    settings = settings or get_settings()
    search = TavilySearch(settings)
    extractor = ClaimExtractor(settings)
    return AgentDependencies(
        search=search.search,
        extract=extractor.extract,
        timeout_seconds=settings.agent_timeout_seconds,
        recent_news_days=settings.recent_news_days,
    )


@lru_cache
def get_research_graph():
    """Return the process-wide graph used for live research."""
    return build_research_graph(build_default_dependencies())


async def run_research_agents(
    query: str,
    user_id: str,
    *,
    job_id: str | None = None,
    dependencies: AgentDependencies | None = None,
) -> ResearchState:
    graph = build_research_graph(dependencies) if dependencies else get_research_graph()
    initial_state: ResearchState = {
        "job_id": job_id or str(uuid4()),
        "user_id": user_id,
        "query": query,
        "agent_results": [],
        "status": "running",
    }
    return await graph.ainvoke(initial_state)
