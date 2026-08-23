# Parallel Research Consensus

A placement-portfolio project that demonstrates a fixed, explainable LangGraph research workflow.
Three specialized agents search concurrently, their claims are compared and source-checked, and a
final answer preserves disagreements instead of hiding them.

## Architecture

```text
Broad Web Agent ───────┐
Academic Agent ────────┼─> compare_findings
Recent News Agent ─────┘          ↓
                         deduplicate_sources
                                  ↓
                       resolve_contradictions
                                  ↓
                         score_confidence
                                  ↓
                            synthesise
```

LangGraph schedules the three async agent nodes in one fan-out superstep. Each uses Tavily with a
different search strategy and an OpenAI structured-output call. A failed or timed-out agent becomes
a structured result, so the remaining evidence can still complete the graph.

The consensus stages conservatively canonicalize URLs, strip tracking parameters, deduplicate by
exact source domain, cluster claims, retain competing positions, and apply this deterministic score:

```text
0.35 agreement + 0.25 source quality + 0.20 source independence
+ 0.10 recency - 0.10 contradiction penalty
```

FastAPI returns a job ID immediately and runs the graph through an in-process background task.
PostgreSQL stores all completed research, while Redis is used only for normalized-query result
caching and per-user fixed-window rate-limit counters. Streamlit polls the API and displays the
answer, confidence, sources, contested points, and stored history.

## Setup

Python 3.11 or newer and PostgreSQL/Redis are required for local service execution.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set at least `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and a long random `SESSION_SECRET`. `.env.example` documents the model,
timeout, search limit, confidence, cache TTL, rate-limit, database, and Redis settings. Production
mode rejects development authentication and validates the OAuth/session configuration at startup.

Run the services directly:

```bash
uvicorn app.main:app --reload
streamlit run streamlit_app/app.py
```

Or run the complete stack:

```bash
docker compose up --build
```

The API is available at `http://localhost:8000` and Streamlit at `http://localhost:8501`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/google` | Exchange a Google ID token for a signed API session |
| `POST` | `/research` | Start an owner-scoped research job |
| `GET` | `/research/{job_id}/status` | Poll running/completed/failed status |
| `GET` | `/research/{job_id}` | Read a completed report |
| `GET` | `/research/history` | List the authenticated user's research |
| `GET` | `/health` | Service health check |

All research endpoints require a bearer session. `X-User-ID` is accepted only when development
authentication is explicitly enabled. Ownership is checked for both report and history access.

## Tests and quality checks

```bash
pytest -q -W error
ruff check .
ruff format --check .
```

The targeted suite covers all-agent success, isolated failure/timeout, empty search results,
malformed LLM output, agreement and disagreement, duplicate-source independence, contradiction
preservation, confidence scoring, authentication/ownership, cache hit/miss behavior, and persistence
after a simulated restart.

## Evaluation

`evaluation/questions.json` contains a fixed 20-question set spanning settled, academic, current,
contested, and source-diversity topics. With the API running and a valid bearer session:

```bash
EVALUATION_BEARER_TOKEN=... python -m evaluation.run_evaluation
```

The ignored `evaluation/results.json` records reports plus latency, cache hit rate, source diversity,
and contradiction counts. Claim accuracy, citation correctness, contradiction detection quality, and
confidence-tier quality are initialized as unscored manual fields. After reviewing them on a 0–1
scale, recalculate the summary with:

```bash
python -m evaluation.run_evaluation --summarize-only evaluation/results.json
```

No benchmark scores are claimed until a real evaluation run has been completed and reviewed.

## Engineering decisions and limitations

- The graph always has exactly three agents; it is intentionally not a generic agent framework.
- Query caching is normalized exact-text matching, not semantic search.
- Source identity uses canonical URLs and exact domains; publisher-lineage matching is out of scope.
- Confidence is a transparent deterministic heuristic, not a trained model.
- Background jobs are process-local; Redis is deliberately not a queue or broker.
- Database tables are initialized with SQLAlchemy `create_all`; schema migrations are not included.
- There is no conversational memory, vector database, general RAG layer, task queue, or deployment
  infrastructure.
- External search and LLM quality, availability, and cost remain service dependencies.

These constraints keep the project small enough to explain and draw in an interview while still
demonstrating orchestration, concurrency, failure isolation, structured AI output, persistence,
caching, authentication, and meaningful reliability tests.
