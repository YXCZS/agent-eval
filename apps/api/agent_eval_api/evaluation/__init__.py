"""Public evaluation engine building blocks."""

from .adapters import (
    ADAPTERS,
    AgentEvalsAdapter,
    DeepEvalAdapter,
    PromptfooAdapter,
    RagasAdapter,
    ThirdPartyAdapter,
    ThirdPartyAdapterError,
    evaluate_adapter,
)
from .aggregation import aggregate_run_scores
from .base import (
    EvaluationContext,
    Evaluator,
    EvaluatorConfigurationError,
    EvaluatorOutcome,
)
from .deterministic import DETERMINISTIC_EVALUATORS, evaluate_deterministic
from .future_adapters import (
    FUTURE_ADAPTER_CAPABILITIES,
    FUTURE_ADAPTERS,
    FutureAdapter,
    FutureAdapterError,
    get_future_adapter,
    list_future_adapter_capabilities,
)
from .judge import (
    DEFAULT_RUBRICS,
    JudgeDecision,
    JudgeProviderConfig,
    JudgeProviderError,
    evaluate_llm_judge,
)
from .prompt_metrics import (
    EmbeddingProviderConfig,
    EmbeddingProviderError,
    evaluate_prompt_deterministic,
    semantic_similarity,
)
from .scoring import evaluate_and_persist_scores

__all__ = [
    "ADAPTERS",
    "AgentEvalsAdapter",
    "aggregate_run_scores",
    "DETERMINISTIC_EVALUATORS",
    "EvaluationContext",
    "EmbeddingProviderConfig",
    "EmbeddingProviderError",
    "DeepEvalAdapter",
    "Evaluator",
    "EvaluatorConfigurationError",
    "EvaluatorOutcome",
    "evaluate_deterministic",
    "FUTURE_ADAPTER_CAPABILITIES",
    "FUTURE_ADAPTERS",
    "FutureAdapter",
    "FutureAdapterError",
    "get_future_adapter",
    "list_future_adapter_capabilities",
    "DEFAULT_RUBRICS",
    "JudgeDecision",
    "JudgeProviderConfig",
    "JudgeProviderError",
    "PromptfooAdapter",
    "RagasAdapter",
    "ThirdPartyAdapter",
    "ThirdPartyAdapterError",
    "evaluate_adapter",
    "evaluate_and_persist_scores",
    "evaluate_llm_judge",
    "evaluate_prompt_deterministic",
    "semantic_similarity",
]
