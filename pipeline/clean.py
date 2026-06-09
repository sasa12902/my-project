from __future__ import annotations

from datetime import timedelta

from .models import Document, RawItem
from .text import canonical_document_id, content_hash, jaccard, normalize_text


def clean_item(item: RawItem) -> Document | None:
    title = normalize_text(item.title)
    summary = normalize_text(item.summary)
    content = normalize_text(item.content or item.summary)
    if not title and not content:
        return None
    if len(content) < 40:
        content = normalize_text(f"{summary} {content} {title}")
    digest = content_hash(title, content)
    return Document(
        id=canonical_document_id(item, content),
        source_type=item.source_type,
        source_name=item.source_name,
        url=item.url.strip(),
        title=title or content[:80],
        published_at=item.published_at,
        summary=summary or content[:240],
        content=content,
        metadata=dict(item.metadata),
        content_hash=digest,
    )


def deduplicate(documents: list[Document]) -> list[Document]:
    by_hash: dict[str, Document] = {}
    for doc in documents:
        existing = by_hash.get(doc.content_hash)
        if existing is None or len(doc.content) > len(existing.content):
            by_hash[doc.content_hash] = doc

    result: list[Document] = []
    for doc in sorted(by_hash.values(), key=lambda item: item.published_at, reverse=True):
        duplicate_index: int | None = None
        for index, kept in enumerate(result):
            close_dates = abs(doc.published_at - kept.published_at) <= timedelta(days=2)
            if doc.source_type == kept.source_type and close_dates and jaccard(doc.title, kept.title) >= 0.9:
                duplicate_index = index
                break
        if duplicate_index is None:
            result.append(doc)
        elif len(doc.content) > len(result[duplicate_index].content):
            result[duplicate_index] = doc
    return result
