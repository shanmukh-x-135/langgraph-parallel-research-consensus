from typing import Annotated, Literal, NotRequired, TypedDict

from app.research.models import AgentName, ResearchResult


def merge_agent_results(
    left: list[ResearchResult], right: list[ResearchResult]
) -> list[ResearchResult]:
    """Merge concurrent branch results in a stable, interview-friendly order."""
    order = {agent: index for index, agent in enumerate(AgentName)}
    return sorted(left + right, key=lambda result: order[result.agent])


class ResearchState(TypedDict):
    job_id: str
    user_id: str
    query: str
    agent_results: Annotated[list[ResearchResult], merge_agent_results]
    claim_clusters: NotRequired[list[dict]]
    deduplicated_sources: NotRequired[list[dict]]
    contradictions: NotRequired[list[dict]]
    confidence_scores: NotRequired[dict[str, dict]]
    final_answer: NotRequired[str]
    contested_points: NotRequired[list[dict]]
    status: Literal["running", "completed", "failed"]
