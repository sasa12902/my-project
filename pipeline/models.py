from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SourceType = Literal["news", "policy", "price"]


@dataclass(slots=True)
class RawItem:
    source_type: SourceType
    source_name: str
    url: str
    title: str
    published_at: datetime
    summary: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    id: str
    source_type: SourceType
    source_name: str
    url: str
    title: str
    published_at: datetime
    summary: str
    content: str
    metadata: dict[str, Any]
    content_hash: str
    embedding: list[float] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
