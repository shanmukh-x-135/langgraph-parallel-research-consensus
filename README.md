# Parallel Research Consensus

A placement-portfolio project implementing a fixed, explainable LangGraph workflow: three
research strategies run concurrently, then feed a transparent consensus and synthesis pipeline.

## Current status

Milestones 1–6 are implemented: the Broad Web, Academic, and Recent News agents fan out in one
LangGraph superstep, tolerate individual failures/timeouts, then feed structured claim comparison
and contradiction-resolution nodes. A thin FastAPI layer starts background jobs and provides
status, result, and owner-scoped history endpoints. Google ID tokens are exchanged for signed API
sessions. PostgreSQL stores users, sessions, agent runs, claims, clusters, contradictions, and final
reports so completed research survives restarts. Redis provides TTL result caching and per-user
fixed-window rate limiting only. Confidence improvements and UI remain deferred.

## Current research architecture

```text
                    ┌─ agent_broad ────┐
START ──────────────┼─ agent_academic ─┼─> compare_findings
                    └─ agent_recent ────┘          |
                                         resolve_contradictions ─> END
```

LangGraph schedules the three async agent nodes concurrently. Each agent uses Tavily with a
distinct search strategy and an OpenAI structured-output call to extract source-backed claims.

## Local setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest
```

Set `OPENAI_API_KEY` and `TAVILY_API_KEY` in `.env` before running a live research request.

Run the API with `uvicorn app.main:app --reload`. Protected requests use bearer sessions returned
by `POST /auth/google`. An `X-User-ID` header is accepted only when development authentication is
explicitly enabled; production mode always requires a bearer session.
