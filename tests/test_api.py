from fastapi.testclient import TestClient

from app.api.jobs import InMemoryJobStore
from app.main import create_app
from app.research.models import AgentName, AgentStatus, ResearchResult

USER_HEADERS = {"X-User-ID": "user-1"}


async def successful_runner(query, user_id, *, job_id=None):
    return {
        "job_id": job_id,
        "user_id": user_id,
        "query": query,
        "agent_results": [
            ResearchResult(
                agent=agent,
                strategy="test",
                status=AgentStatus.SUCCEEDED,
            )
            for agent in AgentName
        ],
        "claim_clusters": [],
        "contradictions": [],
        "contested_points": [],
        "status": "running",
    }


def make_test_app(runner=successful_runner):
    return create_app(research_runner=runner, job_store=InMemoryJobStore())


def test_health_is_public():
    client = TestClient(make_test_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_research_job_status_result_and_history_flow():
    client = TestClient(make_test_app())

    started = client.post("/research", json={"query": "What changed?"}, headers=USER_HEADERS)
    assert started.status_code == 202
    job_id = started.json()["job_id"]

    status_response = client.get(f"/research/{job_id}/status", headers=USER_HEADERS)
    assert status_response.json()["status"] == "completed"

    report = client.get(f"/research/{job_id}", headers=USER_HEADERS)
    assert report.status_code == 200
    assert report.json()["query"] == "What changed?"
    assert len(report.json()["agent_results"]) == 3

    history = client.get("/research/history", headers=USER_HEADERS)
    assert [item["job_id"] for item in history.json()] == [job_id]


def test_user_cannot_fetch_another_users_job():
    client = TestClient(make_test_app())
    started = client.post("/research", json={"query": "Private question"}, headers=USER_HEADERS)
    job_id = started.json()["job_id"]

    other_headers = {"X-User-ID": "user-2"}
    assert client.get(f"/research/{job_id}", headers=other_headers).status_code == 404
    assert client.get(f"/research/{job_id}/status", headers=other_headers).status_code == 404
    assert client.get("/research/history", headers=other_headers).json() == []


def test_protected_routes_require_local_identity():
    client = TestClient(make_test_app())
    assert client.post("/research", json={"query": "Question"}).status_code == 401
    assert client.get("/research/history").status_code == 401


def test_background_failure_is_reported():
    async def failing_runner(query, user_id, *, job_id=None):
        raise RuntimeError("provider down")

    client = TestClient(make_test_app(failing_runner))
    started = client.post("/research", json={"query": "Question"}, headers=USER_HEADERS)
    job_id = started.json()["job_id"]

    response = client.get(f"/research/{job_id}/status", headers=USER_HEADERS)
    assert response.json()["status"] == "failed"
    assert "RuntimeError" in response.json()["error"]
    assert client.get(f"/research/{job_id}", headers=USER_HEADERS).status_code == 409
