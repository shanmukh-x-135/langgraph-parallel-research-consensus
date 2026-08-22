from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AgentName(StrEnum):
    BROAD = "broad_web"
    ACADEMIC = "academic"
    RECENT = "recent_news"


class AgentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class SearchSource(BaseModel):
    title: str
    url: HttpUrl
    snippet: str = ""
    published_at: datetime | None = None


class Claim(BaseModel):
    statement: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    source_urls: list[HttpUrl] = Field(min_length=1)


class ExtractedClaims(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class ResearchResult(BaseModel):
    agent: AgentName
    strategy: str
    status: AgentStatus
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SearchSource] = Field(default_factory=list)
    error: str | None = None


class ClaimReference(BaseModel):
    agent: AgentName
    statement: str
    evidence: str
    source_urls: list[HttpUrl] = Field(min_length=1)


class ClaimCluster(BaseModel):
    cluster_id: str
    topic: str
    summary: str
    claims: list[ClaimReference] = Field(min_length=1)
    supporting_agents: list[AgentName] = Field(default_factory=list)
    agent_agreement: int = Field(ge=1, le=3)


class ClusteredClaims(BaseModel):
    clusters: list[ClaimCluster] = Field(default_factory=list)


class ContradictionPosition(BaseModel):
    statement: str
    supporting_agents: list[AgentName] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    source_urls: list[HttpUrl] = Field(min_length=1)


class Contradiction(BaseModel):
    cluster_id: str
    disputed_claim: str
    positions: list[ContradictionPosition] = Field(min_length=2)


class DetectedContradictions(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)


class SourceRecord(BaseModel):
    raw_url: HttpUrl
    canonical_url: HttpUrl
    domain: str
    source_identity: str
    citing_agents: list[AgentName]


class ConfidenceScore(BaseModel):
    claim_summary: str
    agreement_score: float = Field(ge=0, le=1)
    source_quality_score: float = Field(ge=0, le=1)
    independence_score: float = Field(ge=0, le=1)
    recency_score: float = Field(ge=0, le=1)
    contradiction_penalty: float = Field(ge=0, le=1)
    final_score: float = Field(ge=0, le=1)
    tier: Literal["high", "medium", "low"]
