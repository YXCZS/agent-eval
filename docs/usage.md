# Product Usage

## Main workflow

1. Register a Prompt Agent or an already-running HTTP Agent under **Agents**.
2. Create a Dataset manually or import CSV, JSON, or JSONL under **Datasets**.
3. Review field mapping and validation errors before confirming the import.
4. Select an Agent Version, Dataset Version, and Evaluator Versions under
   **Evaluation runs**.
5. Open **Reports** after the run finishes, inspect failed cases and their
   trace timeline, then evaluate a Regression Gate.

Every run freezes its agent, dataset, evaluator, prompt, model, judge, and
sampling configuration. Editing a dataset creates a new Dataset Version.

## HTTP Agent protocol

The platform calls the configured endpoint with a JSON `POST /run` request:

```json
{
  "input": "Cancel order 42",
  "variables": {},
  "messages": [],
  "metadata": {"run_id": "...", "case_id": "..."},
  "trace_id": "..."
}
```

The response must be a JSON object containing `output`. Optional fields are
`tool_calls`, `usage`, and a canonical `trace` object:

```json
{
  "output": {"status": "cancelled"},
  "tool_calls": [
    {"name": "search_order", "arguments": {"order_id": "42"}, "order": 0}
  ],
  "usage": {"input_tokens": 20, "output_tokens": 8, "cost": 0.001},
  "trace": {"trace_id": "...", "spans": []}
}
```

The endpoint must be reachable from the API container. With Compose, use a
service name such as `http://order-agent:8103/run`, not `localhost`.

## Dataset fields

All import formats map to the same case model:

| Field | Purpose |
|---|---|
| `id` | Stable case identifier, required and unique per version |
| `input` | String or structured input sent to the Agent |
| `variables` | Prompt template variables |
| `messages` | Optional multi-turn chat history |
| `expected_output` | Reference answer or structured result |
| `output_schema` | JSON Schema for structured output validation |
| `criteria` | Natural-language evaluation criteria |
| `expected_tools` | Expected tool names, arguments, and order |
| `expected_state` | Expected business state, such as `{"status":"cancelled"}` |
| `retrieval_context` | Reference documents for RAG metrics |
| `metadata` | Category, difficulty, tags, and custom grouping fields |

CSV values for structured fields should contain valid JSON. JSONL is preferred
when cases include nested messages, tools, or retrieval context.

## Evaluators and scores

Deterministic evaluators include task success, tool correctness, argument
correctness, policy compliance, JSON Schema, exact match, semantic similarity,
latency, token usage, and cost. LLM Judge evaluators store the judge model,
rubric, raw decision, and normalized score. DeepEval, Ragas, Promptfoo, and
AgentEvals can be configured as optional adapters.

Scores have an explicit status: `passed`, `failed`, `missing`, `error`, or
`not_run`. Missing and error scores are never silently treated as passing.

## API and gate

Browser requests use `X-Workspace-Session` in development. Agent and CI calls
should use a project API key in `X-Project-Key`.

```powershell
$headers = @{ "X-Workspace-Session" = "dev:project-1:development-session-secret" }
Invoke-RestMethod http://127.0.0.1:8000/projects/project-1/reports -Headers $headers
```

The machine-readable gate endpoint is:

```text
POST /projects/{project_id}/runs/{run_id}/regression-gate
```

It returns `passed`, `failed`, `indeterminate`, or `incomplete`, including
actual values, thresholds, missing/error counts, and failed case IDs.

## Trace to dataset case

A saved trace can be converted into a new versioned case. Select the input
span, output span, and tool spans; the resulting case records `source_trace_id`.
This lets production failures become regression coverage without copying opaque
framework-specific execution state into the dataset.
