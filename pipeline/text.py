from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import RawItem

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = TAG_RE.sub(" ", value)
    value = value.replace("\u00a0", " ")
    return SPACE_RE.sub(" ", value).strip()


def normalize_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            urlencode(query_pairs, doseq=True),
            "",
        )
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_document_id(item: RawItem, content: str) -> str:
    normalized_url = normalize_url(item.url)
    if normalized_url:
        return sha256_text(f"{item.source_type}|{normalized_url}")
    key = "|".join(
        [
            item.source_type,
            normalize_text(item.title).lower(),
            item.published_at.date().isoformat(),
            normalize_text(content).lower()[:512],
        ]
    )
    return sha256_text(key)


def content_hash(title: str, content: str) -> str:
    text = normalize_text(f"{title}\n{content}").lower()
    return sha256_text(text)


def tokenize(value: str) -> list[str]:
    value = normalize_text(value).lower()
    tokens = TOKEN_RE.findall(value)
    chinese_chars = [tok for tok in tokens if len(tok) == 1 and "\u4e00" <= tok <= "\u9fff"]
    compact_zh = "".join(chinese_chars)
    grams: list[str] = []
    if compact_zh:
        grams.extend(compact_zh[i : i + 2] for i in range(max(0, len(compact_zh) - 1)))
        grams.extend(compact_zh[i : i + 3] for i in range(max(0, len(compact_zh) - 2)))
    words = [tok for tok in tokens if not (len(tok) == 1 and "\u4e00" <= tok <= "\u9fff")]
    return [*words, *grams]


def sentence_split(value: str) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?\.])\s+", text)
    if len(parts) == 1:
        parts = re.split(r"[。！？!?]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def jaccard(a: str, b: str) -> float:
    a_tokens = set(tokenize(a))
    b_tokens = set(tokenize(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
