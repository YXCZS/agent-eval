# RAG Agent Example

Start with `uvicorn examples.rag_agent.app:app --port 8102`. The agent returns
a source-grounded answer, a retrieval tool call, and retrieval context through
the workbench `POST /run` protocol.
