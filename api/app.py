"""
FastAPI application factory.
Serves the dashboard API endpoints with CORS and rate limiting.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware import limiter


def create_app() -> FastAPI:
    app = FastAPI(title="SWE-Jobs API", version="2.0.0")

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — allow dashboard origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten to GitHub Pages URL in production
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Register routes
    from api.routes_jobs import router as jobs_router
    from api.routes_stats import router as stats_router
    app.include_router(jobs_router, prefix="/api/jobs")
    app.include_router(stats_router, prefix="/api/stats")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
