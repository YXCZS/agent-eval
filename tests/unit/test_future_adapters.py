import pytest
from pydantic import ValidationError

from agent_eval_api.contracts import (
    AdapterInvocation,
    AdapterLifecycle,
    DatasetCase,
)
from agent_eval_api.evaluation import (
    FUTURE_ADAPTER_CAPABILITIES,
    FutureAdapterError,
    get_future_adapter,
)


def test_future_capabilities_declare_external_boundaries_without_claiming_availability() -> None:
    capabilities = {item.adapter_id: item for item in FUTURE_ADAPTER_CAPABILITIES}

    assert set(capabilities) == {
        "promptfoo-safety",
        "giskard-safety",
        "garak-safety",
        "agentbench",
        "webarena",
        "osworld",
    }
    assert all(item.lifecycle is AdapterLifecycle.PLANNED for item in capabilities.values())
    assert capabilities["agentbench"].requires_external_environment is True
    assert capabilities["agentbench"].supports_ci is False
    assert capabilities["promptfoo-safety"].supports_ci is True


@pytest.mark.asyncio
async def test_planned_adapter_returns_explicit_unavailable_error() -> None:
    adapter = get_future_adapter("osworld")
    invocation = AdapterInvocation(
        adapter_id="osworld",
        run_id="run-1",
        agent_version_id="agent-v1",
        dataset_version_id="dataset-v1",
        cases=[DatasetCase(id="case-1", input="open settings")],
    )

    with pytest.raises(FutureAdapterError) as raised:
        await adapter.execute(invocation)

    assert raised.value.adapter_id == "osworld"
    assert raised.value.error_type == "adapter_unavailable"


def test_unknown_future_adapter_is_configuration_error() -> None:
    with pytest.raises(FutureAdapterError, match="unknown future adapter") as raised:
        get_future_adapter("not-registered")
    assert raised.value.error_type == "invalid_configuration"


def test_adapter_invocation_requires_at_least_one_case() -> None:
    with pytest.raises(ValidationError):
        AdapterInvocation(
            adapter_id="agentbench",
            run_id="run-1",
            agent_version_id="agent-v1",
            dataset_version_id="dataset-v1",
            cases=[],
        )
