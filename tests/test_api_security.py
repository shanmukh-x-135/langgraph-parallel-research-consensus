import pytest
from fastapi.testclient import TestClient

from app.api.auth import GoogleIdentity
from app.api.jobs import InMemoryJobStore
from app.cache.redis_services import InMemoryCacheRateLimiter
from app.core.config import Settings
from app.main import create_app
from app.research.models import AgentName, AgentStatus, ResearchResult


async def successful_runner(query, user_id, *, job_id=None):
    return {
        "job_id": job_id,
        "user_id": user_id,
        "query": query,
        "agent_results": [
            ResearchResult(agent=agent, strategy="test", status=AgentStatus.SUCCEEDED)
            for agent in AgentName
        ],
        "claim_clusters": [],
        "contradictions": [],
        "contested_points": [],
        "deduplicated_sources": [],
        "confidence_scores": {},
        "final_answer": "Answer",
        "status": "completed",
    }


def production_app():
    settings = Settings(
        _env_file=None,
        app_env="production",
        google_client_id="google-client",
        session_secret="secure-test-session-secret-at-least-32-characters",
    )
    return create_app(
        research_runner=successful_runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=InMemoryCacheRateLimiter(),
        settings=settings,
    )


def bearer(app, user_id):
    token = app.state.session_tokens.issue(
        GoogleIdentity(id=user_id, email=f"{user_id}@example.com", name=user_id)
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("post", "/research", {"query": "Protected question"}),
        ("get", "/research/history", None),
        ("get", "/research/job-id/status", None),
        ("get", "/research/job-id", None),
    ],
)
def test_every_research_endpoint_requires_production_bearer_auth(method, path, json):
    client = TestClient(production_app())
    response = client.request(method, path, json=json)
    assert response.status_code == 401


def test_bearer_authenticated_user_cannot_access_another_users_research():
    app = production_app()
    client = TestClient(app)
    owner_headers = bearer(app, "owner")
    other_headers = bearer(app, "other-user")

    started = client.post("/research", json={"query": "Owner-only research"}, headers=owner_headers)
    job_id = started.json()["job_id"]

    assert client.get(f"/research/{job_id}", headers=other_headers).status_code == 404
    assert client.get(f"/research/{job_id}/status", headers=other_headers).status_code == 404
    assert client.get("/research/history", headers=other_headers).json() == []
    assert client.get(f"/research/{job_id}", headers=owner_headers).status_code == 200
