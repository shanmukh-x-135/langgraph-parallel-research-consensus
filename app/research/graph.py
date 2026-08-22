from functools import lru_cache
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings, get_settings
from app.research.agents import AgentDependencies, create_agent_nodes
from app.research.consensus import ConsensusAnalyzer, cluster_exact_claims
from app.research.extraction import ClaimExtractor
from app.research.models import AgentStatus
from app.research.search import TavilySearch
from app.research.state import ResearchState

AGENT_NODE_NAMES = ("agent_broad", "agent_academic", "agent_recent")


async def compare_findings(state: ResearchState, dependencies: AgentDependencies) -> dict[str, Any]:
    any_succeeded = any(result.status == AgentStatus.SUCCEEDED for result in state["agent_results"])
    if not any_succeeded:
        return {"claim_clusters": [], "status": "failed"}
    try:
        if dependencies.compare:
            clusters = await dependencies.compare(state["query"], state["agent_results"])
        else:
            clusters = cluster_exact_claims(state["agent_results"])
    except Exception:
        return {"claim_clusters": [], "status": "failed"}
    return {"claim_clusters": clusters, "status": "running"}


async def resolve_contradictions(
    state: ResearchState, dependencies: AgentDependencies
) -> dict[str, Any]:
    if state["status"] == "failed":
        return {"contradictions": [], "contested_points": []}
    try:
        contradictions = (
            await dependencies.resolve(state["query"], state.get("claim_clusters", []))
            if dependencies.resolve
            else []
        )
    except Exception:
        return {"contradictions": [], "contested_points": [], "status": "failed"}
    return {"contradictions": contradictions, "contested_points": contradictions}


def build_research_graph(dependencies: AgentDependencies):
    async def compare_node(state: ResearchState) -> dict[str, Any]:
        return await compare_findings(state, dependencies)

    async def contradiction_node(state: ResearchState) -> dict[str, Any]:
        return await resolve_contradictions(state, dependencies)

    builder = StateGraph(ResearchState)
    for node_name, node in create_agent_nodes(dependencies).items():
        builder.add_node(node_name, node)
        builder.add_edge(START, node_name)
        builder.add_edge(node_name, "compare_findings")
    builder.add_node("compare_findings", compare_node)
    builder.add_node("resolve_contradictions", contradiction_node)
    builder.add_edge("compare_findings", "resolve_contradictions")
    builder.add_edge("resolve_contradictions", END)
    return builder.compile()


def build_default_dependencies(settings: Settings | None = None) -> AgentDependencies:
    settings = settings or get_settings()
    search = TavilySearch(settings)
    extractor = ClaimExtractor(settings)
    consensus = ConsensusAnalyzer(settings)
    return AgentDependencies(
        search=search.search,
        extract=extractor.extract,
        timeout_seconds=settings.agent_timeout_seconds,
        recent_news_days=settings.recent_news_days,
        compare=consensus.compare,
        resolve=consensus.resolve,
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
