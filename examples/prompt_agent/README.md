# Prompt Agent Example

Start with `uvicorn examples.prompt_agent.app:app --port 8101`. The example
implements the workbench `POST /run` protocol with deterministic output, which
makes it useful for exact-match, schema, latency, and cost demonstrations.
