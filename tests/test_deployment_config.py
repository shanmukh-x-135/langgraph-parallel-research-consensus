from pathlib import Path

import yaml


def test_compose_contains_exact_required_services():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    assert set(compose["services"]) == {"fastapi", "streamlit", "postgres", "redis"}
    assert compose["services"]["fastapi"]["depends_on"].keys() == {"postgres", "redis"}
    assert "redis-server" in compose["services"]["redis"]["command"]
    assert not any(term in str(compose).casefold() for term in ("celery", "kubernetes", "broker"))


def test_ci_has_only_required_job_categories():
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "ruff check" in workflow
    assert "ruff format --check" in workflow
    assert "pytest" in workflow
    assert "docker build" in workflow
    assert "deploy" not in workflow.casefold()
