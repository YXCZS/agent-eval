"""Read-only API for declared future adapter capabilities."""

from fastapi import APIRouter

from agent_eval_api.contracts import AdapterCapability
from agent_eval_api.evaluation.future_adapters import list_future_adapter_capabilities

router = APIRouter(prefix="/adapter-capabilities", tags=["adapter-capabilities"])


@router.get("", response_model=list[AdapterCapability])
def list_adapter_capabilities() -> list[AdapterCapability]:
    return list_future_adapter_capabilities()
