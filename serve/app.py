from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from pipeline.qa import answer_question
from pipeline.storage import DEFAULT_DB_PATH, VectorStore

app = FastAPI(
    title="Mining Intelligence Query API",
    description="Natural language query API over mining news, critical minerals policy and price data.",
    version="0.1.0",
)

store = VectorStore(Path(DEFAULT_DB_PATH))


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2, examples=["近 7 天澳洲锂出口政策有何变化?"])
    top_k: int = Field(default=5, ge=1, le=20)


class Context(BaseModel):
    id: str
    score: float
    source_type: str
    source_name: str
    title: str
    published_at: str
    url: str
    snippet: str
    metadata: dict[str, Any]


class QueryResponse(BaseModel):
    question: str
    answer: str
    filters: dict[str, Any]
    contexts: list[Context]


@app.get("/health")
def health() -> dict[str, int | str]:
    return {"status": "ok", "documents": store.count()}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> dict[str, object]:
    return answer_question(store=store, question=request.question, top_k=request.top_k)
