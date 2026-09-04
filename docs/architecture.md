# Architecture and Trade-offs

## Runtime flow

```text
Dataset Case
  -> Evaluation Run freezes versions
  -> one Celery job per CaseExecution
  -> Prompt Runner or HTTP Agent Adapter
  -> canonical Trace and TraceSpan records
  -> deterministic / Judge / third-party evaluator
  -> sample Score records
  -> AggregateMetric and Report
  -> Regression Gate and CI result
```

FastAPI owns project-scoped APIs and database facts. Celery workers execute
independent cases so a timeout or protocol failure does not erase other case
results. Redis is the broker/backend. PostgreSQL is the production database;
SQLite is useful for local tests.

## Canonical model

The persistent hierarchy is:

```text
Project
  Agent -> AgentVersion -> Prompt/Endpoint snapshot
  Dataset -> DatasetVersion -> DatasetCase
  EvaluatorVersion
  EvaluationRun -> CaseExecution -> Trace -> TraceSpan
                         \-> Score -> AggregateMetric
```

Agent, dataset, and evaluator versions used by a run are copied into a
configuration snapshot. This costs storage but makes a historical report
explainable after the current configuration changes.

Trace spans use platform kinds such as `agent`, `prompt`, `llm`, `tool`,
`tool_result`, `retrieval`, `guardrail`, and `evaluator`. OpenTelemetry and
OpenInference-compatible fields are mapped into attributes while unknown
vendor fields remain in extensions.

## Evaluator boundary

Deterministic checks run locally and are preferred for gates. LLM Judge is
explicitly labeled as model-based and stores rubric/model/raw result metadata.
Third-party libraries are behind adapters that map their inputs and results to
normalized scores; missing optional packages return an adapter error instead of
an invented score.

Future safety scanners and environment benchmarks use a separate capability
contract exposed at `GET /adapter-capabilities`. A declaration says whether an
adapter is planned, what case fields it needs, what metrics it returns, whether
it needs an external environment, and whether it is suitable for CI. This keeps
AgentBench, WebArena, and OSWorld out of the first release runtime until their
isolated environments are provisioned.

## Privacy and security

The platform never executes uploaded agent source code. HTTP credentials and
LLM keys are configuration secrets, not trace fields. Trace input/output is
redacted by configured field names and bounded by size limits. Project access
is checked on every project-scoped route. Browser sessions and project API
keys are separate principal types, and audit records are kept for manual score
changes.

## Deliberate trade-offs

- A shared Dataset Case model supports Prompt, RAG, Tool, and multi-turn data,
  while type-specific evaluators enforce required fields.
- JSON columns preserve evolving agent payloads, while IDs, versions, statuses,
  and relationships remain relational for filtering and integrity.
- Per-case jobs improve isolation and recovery, at the cost of queue overhead.
- No universal agent score is produced. Reports show dimensions separately;
  only configured metrics and hard gates affect release decisions.
- The first release uses OpenAI-compatible LLM endpoints and HTTP Agent
  protocol. A future SDK or provider layer can reuse the same canonical trace.
