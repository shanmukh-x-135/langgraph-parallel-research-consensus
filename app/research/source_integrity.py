from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import Settings
from app.research.models import (
    AgentName,
    AgentStatus,
    ClaimCluster,
    ConfidenceScore,
    Contradiction,
    ResearchResult,
    SourceRecord,
)

TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
HIGH_QUALITY_DOMAINS = {
    "arxiv.org",
    "jstor.org",
    "nature.com",
    "ncbi.nlm.nih.gov",
    "science.org",
    "ssrn.com",
}


def canonicalize_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    port = parsed.port
    netloc = host if port in {None, 80, 443} else f"{host}:{port}"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
        )
    )
    path = parsed.path or "/"
    canonical = urlunsplit((parsed.scheme.casefold(), netloc, path, query, ""))
    return canonical, host


def deduplicate_sources(results: list[ResearchResult]) -> list[SourceRecord]:
    grouped: dict[str, list[tuple[AgentName, str, str]]] = defaultdict(list)
    for result in results:
        if result.status != AgentStatus.SUCCEEDED:
            continue
        for source in result.sources:
            canonical, domain = canonicalize_url(str(source.url))
            grouped[domain].append((result.agent, str(source.url), canonical))

    records: list[SourceRecord] = []
    for domain, entries in sorted(grouped.items()):
        agents = sorted({entry[0] for entry in entries}, key=list(AgentName).index)
        records.append(
            SourceRecord(
                raw_url=entries[0][1],
                canonical_url=entries[0][2],
                domain=domain,
                source_identity=domain,
                citing_agents=agents,
            )
        )
    return records


def _quality(domain: str) -> float:
    if domain.endswith(".gov") or domain.endswith(".edu") or domain in HIGH_QUALITY_DOMAINS:
        return 1.0
    if domain.endswith(".org"):
        return 0.7
    return 0.5


def _recency(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age_days = max(0, (now - published_at).days)
    if age_days <= 30:
        return 1.0
    if age_days <= 365:
        return 0.7
    return 0.3


def score_claims(
    clusters: list[ClaimCluster],
    results: list[ResearchResult],
    contradictions: list[Contradiction],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, ConfidenceScore]:
    now = now or datetime.now(UTC)
    source_by_url = {
        str(source.url): source
        for result in results
        if result.status == AgentStatus.SUCCEEDED
        for source in result.sources
    }
    contradicted = {item.cluster_id for item in contradictions}
    scores: dict[str, ConfidenceScore] = {}
    for cluster in clusters:
        cited_urls = [str(url) for claim in cluster.claims for url in claim.source_urls]
        identities = {canonicalize_url(url)[1] for url in cited_urls if canonicalize_url(url)[1]}
        qualities = [_quality(canonicalize_url(url)[1]) for url in cited_urls]
        recencies = [
            _recency(source_by_url[url].published_at, now)
            for url in cited_urls
            if url in source_by_url
        ]
        agreement = min(1.0, cluster.agent_agreement / 3)
        independence = min(1.0, len(identities) / len(cited_urls)) if cited_urls else 0.0
        quality = sum(qualities) / len(qualities) if qualities else 0.0
        recency = sum(recencies) / len(recencies) if recencies else 0.5
        penalty = 1.0 if cluster.cluster_id in contradicted else 0.0
        final = (
            settings.confidence_weight_agreement * agreement
            + settings.confidence_weight_source_quality * quality
            + settings.confidence_weight_independence * independence
            + settings.confidence_weight_recency * recency
            - settings.confidence_weight_contradiction * penalty
        )
        final = round(max(0.0, min(1.0, final)), 4)
        tier = (
            "high"
            if final >= settings.confidence_threshold_high
            else "medium"
            if final >= settings.confidence_threshold_medium
            else "low"
        )
        scores[cluster.cluster_id] = ConfidenceScore(
            claim_summary=cluster.summary,
            agreement_score=round(agreement, 4),
            source_quality_score=round(quality, 4),
            independence_score=round(independence, 4),
            recency_score=round(recency, 4),
            contradiction_penalty=penalty,
            final_score=final,
            tier=tier,
        )
    return scores
