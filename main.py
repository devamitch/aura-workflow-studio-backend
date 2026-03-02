from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from auth import keys_router, router as auth_router
from config import get_settings
from database import Base, engine
from middleware import configure_middlewares
from pipeline_run import router as pipeline_run_router
from pipelines import router as pipelines_router
from rag import router as rag_router
from schemas import ParseResponse, PipelinePayload, is_dag


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    configure_middlewares(app, settings)

    @app.get("/")
    def read_root():
        return {"service": "Aura API", "ok": True}

    @app.get("/health")
    def health_check():
        return {"status": "ok", "service": "Aura AI Backend"}

    @app.get("/api/v1/status")
    def status_check():
        return {"api_version": "v1", "status": "operational"}

    @app.post("/pipelines/parse", response_model=ParseResponse)
    def parse_pipeline(payload: PipelinePayload) -> ParseResponse:
        return ParseResponse(
            num_nodes=len(payload.nodes),
            num_edges=len(payload.edges),
            is_dag=is_dag(payload.nodes, payload.edges),
        )

    app.include_router(auth_router)
    app.include_router(keys_router)
    app.include_router(pipelines_router)
    app.include_router(rag_router)
    app.include_router(pipeline_run_router)
    return app


app = create_app()
