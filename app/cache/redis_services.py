import hashlib
import time
from typing import Protocol

import redis.asyncio as redis
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.research.models import ClaimCluster, Contradiction, ResearchResult
from app.research.state import ResearchState


class CachedResearch(BaseModel):
    agent_results: list[ResearchResult] = Field(default_factory=list)
    claim_clusters: list[ClaimCluster] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    contested_points: list[Contradiction] = Field(default_factory=list)
    final_answer: str = ""

    @classmethod
    def from_state(cls, state: ResearchState) -> "CachedResearch":
        return cls(
            agent_results=state["agent_results"],
            claim_clusters=state.get("claim_clusters", []),
            contradictions=state.get("contradictions", []),
            contested_points=state.get("contested_points", []),
            final_answer=state.get("final_answer", ""),
        )

    def to_state(self, job_id: str, user_id: str, query: str) -> ResearchState:
        return {
            "job_id": job_id,
            "user_id": user_id,
            "query": query,
            "agent_results": self.agent_results,
            "claim_clusters": self.claim_clusters,
            "contradictions": self.contradictions,
            "contested_points": self.contested_points,
            "final_answer": self.final_answer,
            "status": "running",
        }


class CacheRateLimiter(Protocol):
    async def initialize(self) -> None: ...

    async def dispose(self) -> None: ...

    async def get_cached(self, query: str) -> CachedResearch | None: ...

    async def cache_result(self, query: str, state: ResearchState) -> None: ...

    async def allow_research(self, user_id: str) -> bool: ...


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


class RedisServices:
    """Redis is used only for result caching and per-user counters."""

    def __init__(self, settings: Settings) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        self._cache_ttl = settings.redis_cache_ttl_seconds
        self._rate_limit = settings.rate_limit_jobs
        self._window = settings.rate_limit_window_seconds

    async def initialize(self) -> None:
        await self._client.ping()

    async def dispose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _cache_key(query: str) -> str:
        digest = hashlib.sha256(normalize_query(query).encode()).hexdigest()
        return f"research:cache:{digest}"

    async def get_cached(self, query: str) -> CachedResearch | None:
        value = await self._client.get(self._cache_key(query))
        return CachedResearch.model_validate_json(value) if value else None

    async def cache_result(self, query: str, state: ResearchState) -> None:
        cached = CachedResearch.from_state(state)
        await self._client.set(self._cache_key(query), cached.model_dump_json(), ex=self._cache_ttl)

    async def allow_research(self, user_id: str) -> bool:
        window_id = int(time.time()) // self._window
        key = f"research:rate:{user_id}:{window_id}"
        async with self._client.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, self._window + 1)
            count, _ = await pipeline.execute()
        return int(count) <= self._rate_limit


class InMemoryCacheRateLimiter:
    """Deterministic test replacement; production always uses RedisServices."""

    def __init__(self, rate_limit: int = 100) -> None:
        self.cache: dict[str, CachedResearch] = {}
        self.counters: dict[str, int] = {}
        self.rate_limit = rate_limit

    async def initialize(self) -> None:
        return None

    async def dispose(self) -> None:
        return None

    async def get_cached(self, query: str) -> CachedResearch | None:
        return self.cache.get(normalize_query(query))

    async def cache_result(self, query: str, state: ResearchState) -> None:
        self.cache[normalize_query(query)] = CachedResearch.from_state(state)

    async def allow_research(self, user_id: str) -> bool:
        self.counters[user_id] = self.counters.get(user_id, 0) + 1
        return self.counters[user_id] <= self.rate_limit
