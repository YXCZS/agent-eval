"""Adapters that normalize third-party evaluator inputs and results."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module, metadata
from typing import Any

from agent_eval_api.contracts import ScoreDirection, ScoreStatus, TraceSpanKind

from .base import EvaluationContext, EvaluatorOutcome

AdapterRunner = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class ThirdPartyAdapterError(RuntimeError):
    """A missing dependency, execution failure, or malformed third-party result."""

    def __init__(self, adapter: str, error_type: str, message: str) -> None:
        super().__init__(message)
        self.adapter = adapter
        self.error_type = error_type


def _package_version(distribution: str, module_name: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        try:
            module = import_module(module_name)
        except ImportError as exc:
            raise ThirdPartyAdapterError(
                module_name,
                "adapter_unavailable",
                f"optional dependency '{distribution}' is not installed",
            ) from exc
        raw_version = getattr(module, "__version__", None)
        return str(raw_version) if raw_version is not None else "unknown"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool | list | dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {
            key: _json_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)


def _number(value: Any, *, adapter: str, field: str = "score") -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ThirdPartyAdapterError(
            adapter, "invalid_result", f"third-party {field} must be numeric"
        )
    return float(value)


def _passed(context: EvaluationContext, value: float, explicit: Any = None) -> bool:
    if isinstance(explicit, bool):
        return explicit
    threshold = context.evaluator.default_threshold
    if threshold is None:
        raise ThirdPartyAdapterError(
            context.evaluator.name,
            "invalid_configuration",
            "numeric adapter result requires default_threshold",
        )
    if context.evaluator.direction is ScoreDirection.LOWER_IS_BETTER:
        return value <= threshold
    return value >= threshold


def _outcome(
    context: EvaluationContext,
    *,
    adapter: str,
    version: str,
    metric: str,
    value: float,
    passed: bool,
    explanation: str | None,
    evidence: list[dict[str, Any]],
    raw_result: Any,
) -> EvaluatorOutcome:
    return EvaluatorOutcome(
        metric_name=metric,
        status=ScoreStatus.PASSED if passed else ScoreStatus.FAILED,
        value=value,
        passed=passed,
        explanation=explanation,
        evidence=evidence,
        raw_result={
            "adapter": adapter,
            "library_version": version,
            "metric": metric,
            "result": _json_value(raw_result),
        },
    )


class ThirdPartyAdapter(ABC):
    name: str
    distribution: str
    module_name: str

    def version(self, context: EvaluationContext) -> str:
        configured = context.evaluator.config.get("library_version")
        if configured is not None:
            return str(configured)
        return _package_version(self.distribution, self.module_name)

    @abstractmethod
    def build_input(self, context: EvaluationContext) -> dict[str, Any]: ...

    @abstractmethod
    def normalize(
        self,
        context: EvaluationContext,
        raw_result: Any,
        *,
        version: str,
    ) -> list[EvaluatorOutcome]: ...

    async def evaluate(
        self,
        context: EvaluationContext,
        runner: AdapterRunner | None = None,
    ) -> list[EvaluatorOutcome]:
        version = self.version(context)
        if runner is None:
            raise ThirdPartyAdapterError(
                self.name,
                "adapter_unavailable",
                f"{self.name} execution runner is not configured",
            )
        try:
            result = runner(self.build_input(context))
            if inspect.isawaitable(result):
                result = await result
        except ThirdPartyAdapterError:
            raise
        except Exception as exc:
            raise ThirdPartyAdapterError(
                self.name, "adapter_execution_error", f"{self.name} evaluator failed: {exc}"
            ) from exc
        return self.normalize(context, result, version=version)


class DeepEvalAdapter(ThirdPartyAdapter):
    name = "deepeval"
    distribution = "deepeval"
    module_name = "deepeval"

    def build_input(self, context: EvaluationContext) -> dict[str, Any]:
        return {
            "input": context.case.input,
            "actual_output": context.execution.output,
            "expected_output": context.case.expected_output,
            "retrieval_context": [item.content for item in context.case.retrieval_context],
            "tools_called": [call.model_dump(mode="json") for call in context.execution.tool_calls],
            "metric": context.evaluator.config.get("metric", context.evaluator.name),
        }

    def normalize(
        self, context: EvaluationContext, raw_result: Any, *, version: str
    ) -> list[EvaluatorOutcome]:
        result = _json_value(raw_result)
        if not isinstance(result, Mapping):
            raise ThirdPartyAdapterError(
                self.name, "invalid_result", "DeepEval result must be an object"
            )
        value = _number(result.get("score"), adapter=self.name)
        metric = str(result.get("name") or result.get("metric") or context.evaluator.name)
        passed = _passed(context, value, result.get("success"))
        evidence = (
            [{"evaluation_model": result.get("evaluation_model")}]
            if result.get("evaluation_model")
            else []
        )
        return [
            _outcome(
                context,
                adapter=self.name,
                version=version,
                metric=metric,
                value=value,
                passed=passed,
                explanation=str(result["reason"]) if result.get("reason") is not None else None,
                evidence=evidence,
                raw_result=raw_result,
            )
        ]


class RagasAdapter(ThirdPartyAdapter):
    name = "ragas"
    distribution = "ragas"
    module_name = "ragas"

    def build_input(self, context: EvaluationContext) -> dict[str, Any]:
        return {
            "user_input": context.case.input,
            "response": context.execution.output,
            "reference": context.case.expected_output,
            "retrieved_contexts": [item.content for item in context.case.retrieval_context],
            "metric": context.evaluator.config.get("metric", context.evaluator.name),
        }

    def normalize(
        self, context: EvaluationContext, raw_result: Any, *, version: str
    ) -> list[EvaluatorOutcome]:
        result = _json_value(raw_result)
        if not isinstance(result, Mapping):
            raise ThirdPartyAdapterError(
                self.name, "invalid_result", "Ragas result must be an object"
            )
        metric = str(context.evaluator.config.get("metric", context.evaluator.name))
        raw_value = result.get(metric, result.get("score"))
        value = _number(raw_value, adapter=self.name)
        return [
            _outcome(
                context,
                adapter=self.name,
                version=version,
                metric=metric,
                value=value,
                passed=_passed(context, value),
                explanation=str(result["reason"]) if result.get("reason") is not None else None,
                evidence=[
                    {
                        "input_fields": [
                            "user_input",
                            "response",
                            "reference",
                            "retrieved_contexts",
                        ]
                    }
                ],
                raw_result=raw_result,
            )
        ]


class PromptfooAdapter(ThirdPartyAdapter):
    name = "promptfoo"
    distribution = "promptfoo"
    module_name = "promptfoo"

    def build_input(self, context: EvaluationContext) -> dict[str, Any]:
        return {
            "prompt": context.case.input,
            "vars": context.case.variables,
            "output": context.execution.output,
            "latency_ms": context.evaluator.config.get("latency_ms"),
            "cost": context.execution.usage.get("cost"),
            "assertions": context.evaluator.config.get("assertions", []),
        }

    def normalize(
        self, context: EvaluationContext, raw_result: Any, *, version: str
    ) -> list[EvaluatorOutcome]:
        result = _json_value(raw_result)
        if not isinstance(result, Mapping):
            raise ThirdPartyAdapterError(
                self.name, "invalid_result", "Promptfoo result must be an object"
            )
        raw_components = result.get("componentResults", result.get("results", []))
        components = raw_components if isinstance(raw_components, list) else []
        if not components:
            components = [result]
        outcomes: list[EvaluatorOutcome] = []
        for index, component in enumerate(components):
            if not isinstance(component, Mapping):
                raise ThirdPartyAdapterError(
                    self.name, "invalid_result", "Promptfoo assertion result must be an object"
                )
            assertion = component.get("assertion")
            if isinstance(assertion, Mapping):
                assertion_type = str(assertion.get("type", "assertion"))
            else:
                assertion_type = str(component.get("type", "assertion"))
            metric = str(
                component.get("metric")
                or f"{context.evaluator.name}:{assertion_type}:{index}"
            )
            raw_score = component.get("score")
            if raw_score is None and isinstance(component.get("pass"), bool):
                raw_score = 1.0 if component["pass"] else 0.0
            value = _number(raw_score, adapter=self.name)
            outcomes.append(
                _outcome(
                    context,
                    adapter=self.name,
                    version=version,
                    metric=metric,
                    value=value,
                    passed=_passed(context, value, component.get("pass")),
                    explanation=(
                        str(component["reason"]) if component.get("reason") is not None else None
                    ),
                    evidence=[{"assertion": _json_value(component.get("assertion"))}],
                    raw_result=component,
                )
            )
        return outcomes


class AgentEvalsAdapter(ThirdPartyAdapter):
    name = "agentevals"
    distribution = "agentevals"
    module_name = "agentevals"

    def build_input(self, context: EvaluationContext) -> dict[str, Any]:
        trajectory = []
        if context.trace is not None:
            trajectory = [
                {
                    "kind": span.kind.value,
                    "name": span.name,
                    "input": span.input,
                    "output": span.output,
                }
                for span in context.trace.spans
                if span.kind in {TraceSpanKind.AGENT, TraceSpanKind.TOOL, TraceSpanKind.TOOL_RESULT}
            ]
        return {
            "inputs": context.case.input,
            "outputs": context.execution.output,
            "reference_outputs": {
                "output": context.case.expected_output,
                "tools": [call.model_dump(mode="json") for call in context.case.expected_tools],
            },
            "trajectory": trajectory,
            "metric": context.evaluator.config.get("metric", context.evaluator.name),
        }

    def normalize(
        self, context: EvaluationContext, raw_result: Any, *, version: str
    ) -> list[EvaluatorOutcome]:
        result = _json_value(raw_result)
        if isinstance(result, bool):
            result = {"score": 1.0 if result else 0.0, "pass": result}
        if not isinstance(result, Mapping):
            raise ThirdPartyAdapterError(
                self.name, "invalid_result", "AgentEvals result must be a boolean or object"
            )
        value = _number(result.get("score"), adapter=self.name)
        metric = str(result.get("key") or result.get("metric") or context.evaluator.name)
        passed = _passed(context, value, result.get("pass"))
        return [
            _outcome(
                context,
                adapter=self.name,
                version=version,
                metric=metric,
                value=value,
                passed=passed,
                explanation=str(result["comment"]) if result.get("comment") is not None else None,
                evidence=[{"trajectory_steps": len(self.build_input(context)["trajectory"])}],
                raw_result=raw_result,
            )
        ]


ADAPTERS: dict[str, ThirdPartyAdapter] = {
    "deepeval": DeepEvalAdapter(),
    "ragas": RagasAdapter(),
    "promptfoo": PromptfooAdapter(),
    "agentevals": AgentEvalsAdapter(),
}


async def evaluate_adapter(
    context: EvaluationContext,
    runner: AdapterRunner | None = None,
) -> list[EvaluatorOutcome]:
    adapter_name = str(context.evaluator.config.get("adapter", "")).casefold()
    adapter = ADAPTERS.get(adapter_name)
    if adapter is None:
        raise ThirdPartyAdapterError(
            adapter_name or "unknown",
            "invalid_configuration",
            f"unknown third-party adapter: {adapter_name or '<missing>'}",
        )
    return await adapter.evaluate(context, runner)
