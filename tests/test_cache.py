from fastapi.testclient import TestClient

from app.api.jobs import InMemoryJobStore
from app.cache.redis_services import CachedResearch, InMemoryCacheRateLimiter, normalize_query
from app.main import create_app
from app.research.models import AgentName, AgentStatus, ResearchResult

HEADERS = {"X-User-ID": "cache-user"}


def state(query="Repeated question"):
    return {
        "job_id": "original-job",
        "user_id": "original-user",
        "query": query,
        "agent_results": [
            ResearchResult(agent=agent, strategy="test", status=AgentStatus.SUCCEEDED)
            for agent in AgentName
        ],
        "claim_clusters": [],
        "contradictions": [],
        "contested_points": [],
        "final_answer": "Cached answer",
        "status": "running",
    }


def test_query_normalization_is_straightforward_and_deterministic():
    assert normalize_query("  What   CHANGED?  ") == "what changed?"


def test_cache_hit_bypasses_research_pipeline():
    calls = 0

    async def runner(query, user_id, *, job_id=None):
        nonlocal calls
        calls += 1
        raise AssertionError("cache hit must bypass the graph")

    cache = InMemoryCacheRateLimiter()
    cache_entry = CachedResearch.from_state(state())
    cache.cache[normalize_query("Repeated question")] = cache_entry
    assert cache_entry.final_answer == "Cached answer"
    app = create_app(
        research_runner=runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=cache,
    )
    client = TestClient(app)

    started = client.post("/research", json={"query": "  repeated   QUESTION"}, headers=HEADERS)
    report = client.get(f"/research/{started.json()['job_id']}", headers=HEADERS)

    assert report.status_code == 200
    assert report.json()["final_answer"] == "Cached answer"
    assert report.json()["cache_hit"] is True
    assert calls == 0


def test_cache_miss_executes_pipeline_and_populates_cache():
    calls = 0

    async def runner(query, user_id, *, job_id=None):
        nonlocal calls
        calls += 1
        return state(query)

    cache = InMemoryCacheRateLimiter()
    app = create_app(
        research_runner=runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=cache,
    )
    client = TestClient(app)

    response = client.post("/research", json={"query": "New question"}, headers=HEADERS)

    assert response.status_code == 202
    assert calls == 1
    assert normalize_query("New question") in cache.cache
    report = client.get(f"/research/{response.json()['job_id']}", headers=HEADERS)
    assert report.json()["cache_hit"] is False


def test_per_user_rate_limit_rejects_excess_jobs():
    async def runner(query, user_id, *, job_id=None):
        return state(query)

    app = create_app(
        research_runner=runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=InMemoryCacheRateLimiter(rate_limit=1),
    )
    client = TestClient(app)

    first = client.post("/research", json={"query": "First question"}, headers=HEADERS)
    second = client.post("/research", json={"query": "Second question"}, headers=HEADERS)

    assert first.status_code == 202
    assert second.status_code == 429


def test_cache_errors_do_not_fail_research_job():
    class FailingCache(InMemoryCacheRateLimiter):
        async def get_cached(self, query):
            raise ConnectionError("Redis unavailable")

        async def cache_result(self, query, result):
            raise ConnectionError("Redis unavailable")

    async def runner(query, user_id, *, job_id=None):
        return state(query)

    app = create_app(
        research_runner=runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=FailingCache(),
    )
    client = TestClient(app)

    started = client.post("/research", json={"query": "Resilient question"}, headers=HEADERS)
    report = client.get(f"/research/{started.json()['job_id']}", headers=HEADERS)

    assert report.status_code == 200
    assert report.json()["final_answer"] == "Cached answer"


async def test_rate_limit_counters_are_independent_per_user():
    limiter = InMemoryCacheRateLimiter(rate_limit=1)
    assert await limiter.allow_research("user-1") is True
    assert await limiter.allow_research("user-1") is False
    assert await limiter.allow_research("user-2") is True
