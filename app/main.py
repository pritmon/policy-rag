"""
main.py — FastAPI application entry point.

Exposes two HTTP endpoints:

  POST /chat   — Accept a user question, run it through the RAG pipeline,
                 return a cited answer with any warning flags.

  GET  /health — Quick database connectivity check.
                 Returns 200 OK if Postgres is reachable, 503 if not.
                 Used by Kubernetes readiness and liveness probes.

Request/Response shapes:
  POST /chat
    Request:  {"message": "What is the hotel limit per night?"}
    Response: {"answer": "...", "citations": [...], "flags": [...]}

  GET /health
    Response: {"status": "ok"}
"""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.graph import run_query
from app.guards import check_input
from app.store import health_check

# Set up logging using the level from settings (default: INFO)
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="policy-rag")


class ChatRequest(BaseModel):
    message: str  # the user's question


class ChatResponse(BaseModel):
    answer: str         # the final answer with inline citations
    citations: list[str]  # list of policy section names referenced
    flags: list[str]    # warning flags: "blocked", "ungrounded", "pii_redacted", "no_context"


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    Main endpoint — run a question through the full RAG pipeline.

    Flow:
      1. check_input() — block injection attempts and empty messages
      2. run_query()   — retriever → critic → synthesizer (LangGraph)
      3. Return the answer, citations, and any flags
    """
    # Step 1: safety check — block bad inputs before they reach the LLM
    refusal = check_input(req.message)
    if refusal:
        return ChatResponse(answer=refusal, citations=[], flags=["blocked"])

    # Step 2: run through the full self-correction pipeline
    try:
        result = run_query(req.message)
    except Exception as e:
        logging.exception("Graph error")  # log full traceback server-side
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(**result)


@app.get("/health")
def health():
    """
    Kubernetes health check endpoint.

    Returns 200 {"status": "ok"} if Postgres is reachable.
    Returns 503 if the database is down — Kubernetes will restart the pod.
    """
    if not health_check():
        raise HTTPException(status_code=503, detail="DB unreachable")
    return {"status": "ok"}
