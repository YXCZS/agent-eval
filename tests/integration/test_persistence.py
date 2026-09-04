from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_eval_api.db import (
    AgentRecord,
    AgentVersionRecord,
    Base,
    CaseExecutionRecord,
    DatasetCaseRecord,
    DatasetRecord,
    DatasetVersionRecord,
    EvaluationRunRecord,
    ProjectRecord,
    TraceRecord,
    TraceSpanRecord,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def make_graph(
    session: Session,
) -> tuple[AgentVersionRecord, DatasetCaseRecord, EvaluationRunRecord]:
    project = ProjectRecord(id="project-1", name="demo")
    agent = AgentRecord(id="agent-1", project=project, name="Order agent", agent_type="tool")
    agent_version = AgentVersionRecord(
        id="agent-version-1",
        agent=agent,
        version=1,
        label="v1",
        agent_type="tool",
        endpoint_config={"url": "https://agent.example.test/run"},
    )
    dataset = DatasetRecord(id="dataset-1", project=project, name="orders")
    dataset_version = DatasetVersionRecord(id="dataset-version-1", dataset=dataset, version=1)
    case = DatasetCaseRecord(
        id="case-record-1",
        dataset_version=dataset_version,
        case_key="case-1",
        input_json={"order_id": "42"},
        expected_tools=[{"name": "search_order"}],
    )
    run = EvaluationRunRecord(
        id="run-1",
        project_id=project.id,
        agent_version=agent_version,
        dataset_version=dataset_version,
        total_cases=1,
    )
    session.add_all([project, agent, dataset, run, case])
    session.commit()
    return agent_version, case, run


def test_version_relationships_and_json_fields_are_persisted(session: Session) -> None:
    agent_version, case, run = make_graph(session)

    execution = CaseExecutionRecord(id="execution-1", run=run, dataset_case=case)
    session.add(execution)
    trace = TraceRecord(
        id="trace-1",
        project_id=run.project_id,
        run=run,
        case_id=case.case_key,
        status="completed",
    )
    span = TraceSpanRecord(
        id="span-record-1",
        trace=trace,
        span_id="span-1",
        kind="tool",
        name="search_order",
        status="completed",
        started_at=datetime.now(UTC),
        attributes={"tool.call.arguments": {"order_id": "42"}},
    )
    execution.trace = trace
    session.add_all([execution, trace, span])
    session.commit()

    loaded = session.scalar(
        select(CaseExecutionRecord).where(CaseExecutionRecord.id == execution.id)
    )
    assert loaded is not None
    assert loaded.trace_id == "trace-1"
    assert loaded.dataset_case.expected_tools[0]["name"] == "search_order"
    assert loaded.run.agent_version_id == agent_version.id
    assert loaded.trace.spans[0].attributes["tool.call.arguments"]["order_id"] == "42"


def test_idempotency_and_unique_version_constraints_are_enforced(session: Session) -> None:
    _, case, run = make_graph(session)
    session.add(CaseExecutionRecord(id="execution-1", run=run, dataset_case=case))
    session.commit()

    session.add(CaseExecutionRecord(id="execution-2", run=run, dataset_case=case))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    duplicate_version = AgentVersionRecord(
        id="agent-version-2",
        agent_id="agent-1",
        version=1,
        label="same-v1",
        agent_type="tool",
        endpoint_config={"url": "https://agent.example.test/run"},
    )
    session.add(duplicate_version)
    with pytest.raises(IntegrityError):
        session.commit()


def test_versioned_history_cannot_be_updated(session: Session) -> None:
    agent_version, _, _ = make_graph(session)
    agent_version.label = "mutated"

    with pytest.raises(ValueError, match="immutable"):
        session.commit()
