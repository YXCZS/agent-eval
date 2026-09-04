"""Project-scoped Agent registration and version endpoints."""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_eval_api.auth import AuthContext, get_db, require_project_access
from agent_eval_api.contracts import (
    AgentConnectionTestRequest,
    AgentConnectionTestResponse,
    AgentCreateRequest,
    AgentResponse,
    AgentType,
    AgentVersionCreateRequest,
    AgentVersionResponse,
    EndpointConfig,
    PromptConfig,
)
from agent_eval_api.db import AgentRecord, AgentVersionRecord, ProjectRecord, new_id
from agent_eval_api.runner import AgentAdapterError, PromptRunnerError, run_http_agent, run_prompt

router = APIRouter(prefix="/projects/{project_id}/agents", tags=["agents"])


def get_project(db: Session, project_id: str) -> ProjectRecord:
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


def get_agent(db: Session, project_id: str, agent_id: str) -> AgentRecord:
    agent = db.scalar(
        select(AgentRecord).where(
            AgentRecord.id == agent_id,
            AgentRecord.project_id == project_id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


def version_response(version: AgentVersionRecord) -> AgentVersionResponse:
    return AgentVersionResponse(
        id=version.id,
        agent_id=version.agent_id,
        version=version.version,
        label=version.label,
        agent_type=AgentType(version.agent_type),
        prompt_config=(
            PromptConfig.model_validate(version.prompt_config) if version.prompt_config else None
        ),
        endpoint_config=(
            EndpointConfig.model_validate(version.endpoint_config)
            if version.endpoint_config
            else None
        ),
        enabled=version.enabled,
        created_at=version.created_at,
    )


def agent_response(agent: AgentRecord) -> AgentResponse:
    current_version_id = (
        max(agent.versions, key=lambda item: item.version).id if agent.versions else None
    )
    return AgentResponse(
        id=agent.id,
        project_id=agent.project_id,
        name=agent.name,
        agent_type=AgentType(agent.agent_type),
        description=agent.description,
        active=agent.active,
        current_version_id=current_version_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.post("/connection-test", response_model=AgentConnectionTestResponse)
async def test_agent_connection(
    project_id: str,
    payload: AgentConnectionTestRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentConnectionTestResponse:
    """Run one bounded request without persisting a trace or agent version."""

    get_project(db, project_id)
    started = time.perf_counter()
    try:
        if payload.agent_type is AgentType.PROMPT:
            assert payload.prompt_config is not None
            result = await run_prompt(
                payload.prompt_config,
                payload.variables,
                input_messages=[message.model_dump(mode="json") for message in payload.messages]
                or None,
            )
            return AgentConnectionTestResponse(
                success=True,
                message="Prompt provider responded successfully",
                latency_ms=(time.perf_counter() - started) * 1000,
                output=result.output,
                rendered_prompt=result.rendered_prompt,
                usage={
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.total_tokens,
                    "cost": result.usage.cost,
                },
            )

        assert payload.endpoint_config is not None
        http_result = await run_http_agent(
            payload.endpoint_config,
            payload.input,
            variables=payload.variables,
            messages=[message.model_dump(mode="json") for message in payload.messages] or None,
            run_id="connection-test",
            case_id="connection-test",
            trace_id=f"connection-test-{uuid4().hex}",
        )
        return AgentConnectionTestResponse(
            success=True,
            message="Agent endpoint responded successfully",
            latency_ms=(time.perf_counter() - started) * 1000,
            output=http_result.output,
            usage=http_result.usage,
        )
    except PromptRunnerError as exc:
        return AgentConnectionTestResponse(
            success=False,
            message=str(exc),
            error_type=exc.error_type,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except AgentAdapterError as exc:
        return AgentConnectionTestResponse(
            success=False,
            message=str(exc),
            error_type=exc.error_type,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    project_id: str,
    payload: AgentCreateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentResponse:
    get_project(db, project_id)
    agent = AgentRecord(
        id=new_id(),
        project_id=project_id,
        name=payload.name,
        agent_type=payload.agent_type.value,
        description=payload.description,
    )
    version = AgentVersionRecord(
        id=new_id(),
        agent=agent,
        version=1,
        label=payload.name + " v1",
        agent_type=payload.agent_type.value,
        prompt_config=payload.prompt_config.model_dump(mode="json")
        if payload.prompt_config
        else None,
        endpoint_config=payload.endpoint_config.model_dump(mode="json")
        if payload.endpoint_config
        else None,
    )
    db.add_all([agent, version])
    db.commit()
    db.refresh(agent)
    return agent_response(agent)


@router.get("", response_model=list[AgentResponse])
def list_agents(
    project_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> list[AgentResponse]:
    get_project(db, project_id)
    agents = db.scalars(select(AgentRecord).where(AgentRecord.project_id == project_id)).all()
    return [agent_response(agent) for agent in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
def read_agent(
    project_id: str,
    agent_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentResponse:
    return agent_response(get_agent(db, project_id, agent_id))


@router.post(
    "/{agent_id}/versions", response_model=AgentVersionResponse, status_code=status.HTTP_201_CREATED
)
def create_agent_version(
    project_id: str,
    agent_id: str,
    payload: AgentVersionCreateRequest,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentVersionResponse:
    agent = get_agent(db, project_id, agent_id)
    if payload.agent_type.value != agent.agent_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="agent type cannot change"
        )
    latest = db.scalar(
        select(func.max(AgentVersionRecord.version)).where(AgentVersionRecord.agent_id == agent.id)
    )
    version = AgentVersionRecord(
        id=new_id(),
        agent=agent,
        version=(latest or 0) + 1,
        label=payload.label or f"{agent.name} v{(latest or 0) + 1}",
        agent_type=agent.agent_type,
        prompt_config=payload.prompt_config.model_dump(mode="json")
        if payload.prompt_config
        else None,
        endpoint_config=payload.endpoint_config.model_dump(mode="json")
        if payload.endpoint_config
        else None,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version_response(version)


@router.get("/{agent_id}/versions", response_model=list[AgentVersionResponse])
def list_agent_versions(
    project_id: str,
    agent_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> list[AgentVersionResponse]:
    agent = get_agent(db, project_id, agent_id)
    versions = db.scalars(
        select(AgentVersionRecord)
        .where(AgentVersionRecord.agent_id == agent.id)
        .order_by(AgentVersionRecord.version)
    ).all()
    return [version_response(version) for version in versions]


@router.patch("/{agent_id}/versions/{version_id}/enabled", response_model=AgentVersionResponse)
def set_agent_version_enabled(
    project_id: str,
    agent_id: str,
    version_id: str,
    enabled: bool,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentVersionResponse:
    agent = get_agent(db, project_id, agent_id)
    version = db.scalar(
        select(AgentVersionRecord).where(
            AgentVersionRecord.id == version_id,
            AgentVersionRecord.agent_id == agent.id,
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent version not found")
    version.enabled = enabled
    db.commit()
    db.refresh(version)
    return version_response(version)


@router.patch("/{agent_id}/active", response_model=AgentResponse)
def set_agent_active(
    project_id: str,
    agent_id: str,
    active: bool,
    db: Session = Depends(get_db),  # noqa: B008
    _: AuthContext = Depends(require_project_access),  # noqa: B008
) -> AgentResponse:
    agent = get_agent(db, project_id, agent_id)
    agent.active = active
    db.commit()
    db.refresh(agent)
    return agent_response(agent)
