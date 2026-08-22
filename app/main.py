from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import GoogleVerifier, SessionTokens, verify_google_identity
from app.api.jobs import JobStore, ResearchRunner
from app.api.routes import router
from app.cache.redis_services import CacheRateLimiter, RedisServices
from app.core.config import Settings, get_settings
from app.db.store import DatabaseJobStore
from app.research.graph import run_research_agents


def create_app(
    *,
    research_runner: ResearchRunner = run_research_agents,
    job_store: JobStore | None = None,
    settings: Settings | None = None,
    google_verifier: GoogleVerifier = verify_google_identity,
    cache_rate_limiter: CacheRateLimiter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.app_env == "production":
        if not settings.google_client_id:
            raise ValueError("GOOGLE_CLIENT_ID is required in production")
        if len(settings.session_secret.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters in production")
    owns_store = job_store is None
    store = job_store or DatabaseJobStore(settings.database_url)
    owns_redis = cache_rate_limiter is None
    redis_services = cache_rate_limiter or RedisServices(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await store.initialize()
        try:
            await redis_services.initialize()
            yield
        finally:
            if owns_redis:
                await redis_services.dispose()
            if owns_store:
                await store.dispose()

    application = FastAPI(title="Parallel Research Consensus", version="0.1.0", lifespan=lifespan)
    application.state.research_runner = research_runner
    application.state.job_store = store
    application.state.settings = settings
    application.state.google_verifier = google_verifier
    application.state.session_tokens = SessionTokens(settings)
    application.state.cache_rate_limiter = redis_services
    application.include_router(router)
    return application


app = create_app()
