from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_eval_api.adapter_capabilities import router as adapter_capabilities_router
from agent_eval_api.agents import router as agents_router
from agent_eval_api.annotations import router as annotations_router
from agent_eval_api.auth import AuthContext, require_project_access
from agent_eval_api.comparisons import router as comparisons_router
from agent_eval_api.contracts import AccessCheckResponse, HealthResponse
from agent_eval_api.datasets import router as datasets_router
from agent_eval_api.evaluation_runs import router as evaluation_runs_router
from agent_eval_api.evaluators import router as evaluators_router
from agent_eval_api.regression_gates import router as regression_gates_router
from agent_eval_api.reports import router as reports_router
from agent_eval_api.settings import get_settings
from agent_eval_api.traces import router as traces_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Eval Workbench API",
        version="0.1.0",
        description="Trace-driven evaluation for prompt, RAG, tool, and custom agents.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:13000",
            "http://127.0.0.1:13000",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agents_router)
    app.include_router(adapter_capabilities_router)
    app.include_router(annotations_router)
    app.include_router(datasets_router)
    app.include_router(comparisons_router)
    app.include_router(evaluators_router)
    app.include_router(evaluation_runs_router)
    app.include_router(reports_router)
    app.include_router(regression_gates_router)
    app.include_router(traces_router)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        settings = get_settings()
        return HealthResponse(status="ok", environment=settings.app_env)

    @app.get(
        "/projects/{project_id}/access-check",
        response_model=AccessCheckResponse,
        tags=["auth"],
    )
    def access_check(
        project_id: str,
        auth: AuthContext = Depends(require_project_access),  # noqa: B008
    ) -> AccessCheckResponse:
        return AccessCheckResponse(
            project_id=auth.project_id,
            principal_type=auth.principal_type,
        )

    return app


app = create_app()
