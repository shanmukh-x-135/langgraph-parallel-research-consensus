from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.research.models import ClaimCluster, Contradiction, ResearchResult

JobStatus = Literal["running", "completed", "failed"]


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)


class ResearchStartResponse(BaseModel):
    job_id: str
    status: JobStatus


class ResearchStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None


class ResearchReport(BaseModel):
    job_id: str
    query: str
    status: Literal["completed"] = "completed"
    agent_results: list[ResearchResult]
    claim_clusters: list[ClaimCluster]
    contradictions: list[Contradiction]
    contested_points: list[Contradiction]
    final_answer: str = ""


class ResearchHistoryItem(BaseModel):
    job_id: str
    query: str
    status: JobStatus
    created_at: datetime
    completed_at: datetime | None = None
