# Parallel Research Consensus

A placement-portfolio project implementing a fixed, explainable LangGraph workflow: three
research strategies run concurrently, then feed a transparent consensus and synthesis pipeline.

## Current status

Milestone 1 is implemented: the Broad Web, Academic, and Recent News agents fan out in one
LangGraph superstep, tolerate individual failures/timeouts, and fan in to structured results.
Consensus, API, persistence, cache, authentication, and UI are intentionally deferred to their
PRD milestones.

## Milestone 1 architecture

```text
                    ┌─ agent_broad ────┐
START ──────────────┼─ agent_academic ─┼─> collect_findings ─> END
                    └─ agent_recent ────┘
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
