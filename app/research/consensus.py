import json
import re

from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.research.models import (
    AgentName,
    AgentStatus,
    ClaimCluster,
    ClaimReference,
    ClusteredClaims,
    ConfidenceScore,
    Contradiction,
    ContradictionPosition,
    DetectedContradictions,
    ResearchResult,
    SynthesisOutput,
)


def _normalize_claim(statement: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", statement.casefold()).split())


def cluster_exact_claims(results: list[ResearchResult]) -> list[ClaimCluster]:
    """Conservative fallback: group only textually identical normalized claims."""
    grouped: dict[str, list[ClaimReference]] = {}
    for result in results:
        if result.status != AgentStatus.SUCCEEDED:
            continue
        for claim in result.claims:
            reference = ClaimReference(
                agent=result.agent,
                statement=claim.statement,
                evidence=claim.evidence,
                source_urls=claim.source_urls,
            )
            grouped.setdefault(_normalize_claim(claim.statement), []).append(reference)

    clusters: list[ClaimCluster] = []
    for index, references in enumerate(grouped.values(), start=1):
        agents = sorted({reference.agent for reference in references}, key=list(AgentName).index)
        summary = references[0].statement
        clusters.append(
            ClaimCluster(
                cluster_id=f"cluster_{index}",
                topic=summary,
                summary=summary,
                claims=references,
                supporting_agents=agents,
                agent_agreement=len(agents),
            )
        )
    return clusters


class ConsensusAnalyzer:
    """LLM-assisted semantic clustering with deterministic reference validation."""

    def __init__(self, settings: Settings) -> None:
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for live research")
        model = ChatOpenAI(
            model=settings.agent_model,
            api_key=api_key,
            max_completion_tokens=settings.agent_max_tokens,
            timeout=settings.agent_timeout_seconds,
            max_retries=1,
        )
        self._cluster_model = model.with_structured_output(ClusteredClaims, method="json_schema")
        self._contradiction_model = model.with_structured_output(
            DetectedContradictions, method="json_schema"
        )
        synthesis_model = ChatOpenAI(
            model=settings.synthesis_model,
            api_key=api_key,
            max_completion_tokens=settings.agent_max_tokens,
            timeout=settings.agent_timeout_seconds,
            max_retries=1,
        )
        self._synthesis_model = synthesis_model.with_structured_output(
            SynthesisOutput, method="json_schema"
        )

    async def compare(self, query: str, results: list[ResearchResult]) -> list[ClaimCluster]:
        successful = [result for result in results if result.status == AgentStatus.SUCCEEDED]
        if not any(result.claims for result in successful):
            return []

        payload = [result.model_dump(mode="json") for result in successful]
        prompt = (
            "Group claims that address the same factual proposition. Keep semantically distinct "
            "claims separate. Copy agent names, claim statements, evidence, and source URLs "
            "exactly from the input; do not invent or paraphrase references. A cluster may contain "
            "positions because contradiction detection happens next.\n\n"
            f"Research question: {query}\nAgent results: {json.dumps(payload)}"
        )
        output = await self._cluster_model.ainvoke(prompt)
        if not isinstance(output, ClusteredClaims):
            output = ClusteredClaims.model_validate(output)
        validated = self._validate_clusters(output.clusters, successful)
        return validated or cluster_exact_claims(successful)

    async def resolve(self, query: str, clusters: list[ClaimCluster]) -> list[Contradiction]:
        if not clusters:
            return []
        prompt = (
            "Identify only direct factual conflicts inside each claim cluster. Different details, "
            "emphasis, or missing information are not contradictions. For every real conflict, "
            "copy the cluster_id and the exact competing claim statements. Preserve both sides.\n\n"
            f"Research question: {query}\n"
            f"Claim clusters: {json.dumps([c.model_dump(mode='json') for c in clusters])}"
        )
        output = await self._contradiction_model.ainvoke(prompt)
        if not isinstance(output, DetectedContradictions):
            output = DetectedContradictions.model_validate(output)
        return self._validate_contradictions(output.contradictions, clusters)

    async def synthesize(
        self,
        query: str,
        clusters: list[ClaimCluster],
        contradictions: list[Contradiction],
        confidence_scores: dict[str, ConfidenceScore],
    ) -> str:
        payload = {
            "clusters": [cluster.model_dump(mode="json") for cluster in clusters],
            "contradictions": [item.model_dump(mode="json") for item in contradictions],
            "confidence_scores": {
                key: value.model_dump(mode="json") for key, value in confidence_scores.items()
            },
        }
        prompt = (
            "Write a concise research answer using only the supplied evidence. Cite supporting "
            "source URLs inline. State confidence tiers where useful. Keep every contradiction "
            "visible with both positions; never average competing claims into one conclusion. "
            "If there is no evidence, say that the search found insufficient evidence.\n\n"
            f"Research question: {query}\nResearch data: {json.dumps(payload)}"
        )
        output = await self._synthesis_model.ainvoke(prompt)
        if not isinstance(output, SynthesisOutput):
            output = SynthesisOutput.model_validate(output)
        return output.final_answer

    @staticmethod
    def _validate_clusters(
        proposed: list[ClaimCluster], results: list[ResearchResult]
    ) -> list[ClaimCluster]:
        actual: dict[tuple[AgentName, str], ClaimReference] = {}
        for result in results:
            for claim in result.claims:
                actual[(result.agent, claim.statement)] = ClaimReference(
                    agent=result.agent,
                    statement=claim.statement,
                    evidence=claim.evidence,
                    source_urls=claim.source_urls,
                )

        validated: list[ClaimCluster] = []
        used: set[tuple[AgentName, str]] = set()
        for cluster in proposed:
            references: list[ClaimReference] = []
            for proposed_reference in cluster.claims:
                key = (proposed_reference.agent, proposed_reference.statement)
                if key in actual and key not in used:
                    references.append(actual[key])
                    used.add(key)
            if not references:
                continue
            agents = sorted(
                {reference.agent for reference in references}, key=list(AgentName).index
            )
            validated.append(
                cluster.model_copy(
                    update={
                        "cluster_id": f"cluster_{len(validated) + 1}",
                        "claims": references,
                        "supporting_agents": agents,
                        "agent_agreement": len(agents),
                    }
                )
            )

        missing_results: list[ResearchResult] = []
        for result in results:
            missing_claims = [
                claim for claim in result.claims if (result.agent, claim.statement) not in used
            ]
            if missing_claims:
                missing_results.append(result.model_copy(update={"claims": missing_claims}))
        for fallback in cluster_exact_claims(missing_results):
            validated.append(
                fallback.model_copy(update={"cluster_id": f"cluster_{len(validated) + 1}"})
            )
        return validated

    @staticmethod
    def _validate_contradictions(
        proposed: list[Contradiction], clusters: list[ClaimCluster]
    ) -> list[Contradiction]:
        by_id = {cluster.cluster_id: cluster for cluster in clusters}
        validated: list[Contradiction] = []
        for contradiction in proposed:
            cluster = by_id.get(contradiction.cluster_id)
            if cluster is None:
                continue
            by_statement: dict[str, list[ClaimReference]] = {}
            for reference in cluster.claims:
                by_statement.setdefault(reference.statement, []).append(reference)

            positions: list[ContradictionPosition] = []
            seen_statements: set[str] = set()
            for proposed_position in contradiction.positions:
                statement = proposed_position.statement
                references = by_statement.get(statement, [])
                if not references or statement in seen_statements:
                    continue
                seen_statements.add(statement)
                agents = sorted(
                    {reference.agent for reference in references}, key=list(AgentName).index
                )
                evidence = list(dict.fromkeys(reference.evidence for reference in references))
                urls = list(
                    dict.fromkeys(url for reference in references for url in reference.source_urls)
                )
                positions.append(
                    ContradictionPosition(
                        statement=statement,
                        supporting_agents=agents,
                        evidence=evidence,
                        source_urls=urls,
                    )
                )
            if len(positions) >= 2:
                validated.append(contradiction.model_copy(update={"positions": positions}))
        return validated


def fallback_synthesis(clusters: list[ClaimCluster], contradictions: list[Contradiction]) -> str:
    if not clusters:
        return (
            "The research agents found insufficient source-backed evidence to answer the question."
        )
    lines = [cluster.summary for cluster in clusters]
    if contradictions:
        lines.append(
            "Contested points: "
            + "; ".join(
                f"{item.disputed_claim} ({' versus '.join(p.statement for p in item.positions)})"
                for item in contradictions
            )
        )
    return "\n\n".join(lines)
