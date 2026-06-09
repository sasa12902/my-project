from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .embedding import HashingEmbedder, cosine_similarity
from .models import Document, SourceType
from .text import tokenize

DEFAULT_DB_PATH = Path("data/mining_intel.sqlite3")


@dataclass(slots=True)
class SearchResult:
    document: Document
    score: float


class VectorStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, embedder: HashingEmbedder | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or HashingEmbedder()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    url TEXT,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    summary TEXT,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_published_at ON documents(published_at)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash)")

    def upsert_many(self, documents: Iterable[Document]) -> int:
        rows = []
        for doc in documents:
            text = f"{doc.title}\n{doc.summary}\n{doc.content}"
            doc.embedding = self.embedder.embed(text)
            rows.append(
                (
                    doc.id,
                    doc.source_type,
                    doc.source_name,
                    doc.url,
                    doc.title,
                    doc.published_at.astimezone(timezone.utc).isoformat(),
                    doc.summary,
                    doc.content,
                    json.dumps(doc.metadata, ensure_ascii=False, sort_keys=True),
                    doc.content_hash,
                    json.dumps(doc.embedding),
                    doc.created_at.astimezone(timezone.utc).isoformat(),
                )
            )
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO documents (
                    id, source_type, source_name, url, title, published_at, summary,
                    content, metadata, content_hash, embedding, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_type=excluded.source_type,
                    source_name=excluded.source_name,
                    url=excluded.url,
                    title=excluded.title,
                    published_at=excluded.published_at,
                    summary=excluded.summary,
                    content=excluded.content,
                    metadata=excluded.metadata,
                    content_hash=excluded.content_hash,
                    embedding=excluded.embedding
                """,
                rows,
            )
        return len(rows)

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()
            return int(row["total"])

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_types: list[SourceType] | None = None,
        since: datetime | None = None,
    ) -> list[SearchResult]:
        query_vector = self.embedder.embed(query)
        query_tokens = set(tokenize(query))
        clauses = []
        params: list[str] = []
        if source_types:
            placeholders = ",".join("?" for _ in source_types)
            clauses.append(f"source_type IN ({placeholders})")
            params.extend(source_types)
        if since:
            clauses.append("published_at >= ?")
            params.append(since.astimezone(timezone.utc).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM documents {where}"
        results: list[SearchResult] = []
        with self._connect() as conn:
            for row in conn.execute(sql, params):
                embedding = json.loads(row["embedding"])
                document = self._row_to_document(row)
                lexical_score = self._lexical_score(query_tokens, document)
                score = (0.72 * cosine_similarity(query_vector, embedding)) + (0.28 * lexical_score)
                results.append(SearchResult(document=document, score=score))
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    @staticmethod
    def _lexical_score(query_tokens: set[str], document: Document) -> float:
        if not query_tokens:
            return 0.0
        haystack = " ".join(
            [
                document.title,
                document.summary,
                document.content,
                document.source_name,
                json.dumps(document.metadata, ensure_ascii=False),
            ]
        )
        document_tokens = set(tokenize(haystack))
        if not document_tokens:
            return 0.0
        return len(query_tokens & document_tokens) / len(query_tokens)

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            source_type=row["source_type"],
            source_name=row["source_name"],
            url=row["url"] or "",
            title=row["title"],
            published_at=datetime.fromisoformat(row["published_at"]),
            summary=row["summary"] or "",
            content=row["content"],
            metadata=json.loads(row["metadata"]),
            content_hash=row["content_hash"],
            embedding=json.loads(row["embedding"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
