import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.graph import run_query
from app.guards import check_input
from app.store import health_check

logging.basicConfig(level=settings.log_level)
app = FastAPI(title="policy-rag")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[str]
    flags: list[str]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    refusal = check_input(req.message)
    if refusal:
        return ChatResponse(answer=refusal, citations=[], flags=["blocked"])

    try:
        result = run_query(req.message)
    except Exception as e:
        logging.exception("Graph error")
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(**result)


@app.get("/health")
def health():
    if not health_check():
        raise HTTPException(status_code=503, detail="DB unreachable")
    return {"status": "ok"}
