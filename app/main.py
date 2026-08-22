from fastapi import FastAPI

from app.api.jobs import InMemoryJobStore, ResearchRunner
from app.api.routes import router
from app.research.graph import run_research_agents


def create_app(
    *,
    research_runner: ResearchRunner = run_research_agents,
    job_store: InMemoryJobStore | None = None,
) -> FastAPI:
    application = FastAPI(title="Parallel Research Consensus", version="0.1.0")
    application.state.research_runner = research_runner
    application.state.job_store = job_store or InMemoryJobStore()
    application.include_router(router)
    return application


app = create_app()
