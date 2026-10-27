from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.auth.router import router as auth_router
from app.auth.router import users_router
from app.cases.router import router as cases_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import register_middleware
from app.db.init_db import initialize_database, validate_database_connection
from app.db.session import SessionLocal
from app.documents.router import router as documents_router
from app.organizations.router import router as organizations_router
from app.statements.router import router as statements_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    with SessionLocal() as db:
        initialize_database(db)
    yield


def _find_frontend(configured: str) -> Path | None:
    here = Path(__file__).resolve()
    for c in [configured, str(here.parents[2] / "frontend"), "/app/frontend"]:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend API for the Enterprise Financial Verification Platform.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_middleware(app)
    register_exception_handlers(app)

    @app.get("/health", tags=["Health"])
    def health() -> dict[str, str]:
        with SessionLocal() as db:
            validate_database_connection(db)
        return {"status": "healthy"}

    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(users_router, prefix=settings.api_v1_prefix)
    app.include_router(organizations_router, prefix=settings.api_v1_prefix)
    app.include_router(cases_router, prefix=settings.api_v1_prefix)
    app.include_router(documents_router, prefix=settings.api_v1_prefix)
    app.include_router(statements_router, prefix=settings.api_v1_prefix)

    # Serve the web UI from the same origin (no CORS / setup needed)
    frontend = _find_frontend(settings.frontend_dir)
    if frontend:
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="ui")
    else:

        @app.get("/")
        def root() -> dict[str, str]:
            return {"service": settings.app_name, "status": "running", "docs": "/docs"}

    return app


app = create_app()
