from fastapi import FastAPI

from app.api.auth import GoogleVerifier, SessionTokens, verify_google_identity
from app.api.jobs import InMemoryJobStore, ResearchRunner
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.research.graph import run_research_agents


def create_app(
    *,
    research_runner: ResearchRunner = run_research_agents,
    job_store: InMemoryJobStore | None = None,
    settings: Settings | None = None,
    google_verifier: GoogleVerifier = verify_google_identity,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.app_env == "production":
        if not settings.google_client_id:
            raise ValueError("GOOGLE_CLIENT_ID is required in production")
        if len(settings.session_secret.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters in production")
    application = FastAPI(title="Parallel Research Consensus", version="0.1.0")
    application.state.research_runner = research_runner
    application.state.job_store = job_store or InMemoryJobStore()
    application.state.settings = settings
    application.state.google_verifier = google_verifier
    application.state.session_tokens = SessionTokens(settings)
    application.include_router(router)
    return application


app = create_app()
