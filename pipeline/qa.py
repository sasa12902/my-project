from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import SourceType
from .storage import SearchResult, VectorStore
from .text import sentence_split

SOURCE_KEYWORDS: dict[SourceType, tuple[str, ...]] = {
    "news": ("新闻", "news", "mine", "mining", "项目", "供应"),
    "policy": ("政策", "policy", "strategy", "出口", "export", "监管", "critical minerals"),
    "price": ("价格", "price", "lme", "shfe", "报价", "库存", "铜价", "锌价", "镍价", "锂价", "铁矿石"),
}

QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "澳洲": ("Australia", "Australian"),
    "澳大利亚": ("Australia", "Australian"),
    "中国": ("China",),
    "印尼": ("Indonesia",),
    "秘鲁": ("Peru",),
    "加拿大": ("Canada",),
    "智利": ("Chile",),
    "锂": ("lithium",),
    "铜": ("copper",),
    "锌": ("zinc",),
    "镍": ("nickel",),
    "铁矿石": ("iron ore",),
    "稀土": ("rare earths", "rare earth"),
    "关键矿产": ("critical minerals",),
    "出口": ("export", "export controls", "export review"),
    "政策": ("policy", "strategy", "regulation"),
    "价格": ("price", "benchmark prices"),
    "库存": ("inventories",),
    "需求": ("demand",),
    "补贴": ("subsidy", "processing subsidy"),
    "环境审查": ("environmental review",),
}


def infer_source_types(question: str) -> list[SourceType] | None:
    lowered = question.lower()
    has_policy_intent = any(keyword in lowered for keyword in SOURCE_KEYWORDS["policy"])
    has_price_intent = any(keyword in lowered for keyword in SOURCE_KEYWORDS["price"])
    has_news_intent = any(keyword in lowered for keyword in SOURCE_KEYWORDS["news"])
    if has_policy_intent and not has_price_intent:
        return ["policy"]
    if has_price_intent and not has_policy_intent:
        return ["price"]
    if has_news_intent and not has_policy_intent and not has_price_intent:
        return ["news"]
    matches: list[SourceType] = []
    for source_type, keywords in SOURCE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            matches.append(source_type)
    return matches or None


def expand_query(question: str) -> str:
    additions: list[str] = []
    lowered = question.lower()
    for trigger, expansions in QUERY_EXPANSIONS.items():
        if trigger.lower() in lowered:
            additions.extend(expansions)
    if not additions:
        return question
    unique = list(dict.fromkeys(additions))
    return f"{question} {' '.join(unique)}"


def infer_since(question: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    match = re.search(r"近\s*(\d+)\s*天|last\s+(\d+)\s+days", question, re.IGNORECASE)
    if match:
        days = int(match.group(1) or match.group(2))
        return now - timedelta(days=days)
    if "近一周" in question or "过去一周" in question:
        return now - timedelta(days=7)
    if "近30天" in question or "近 30 天" in question:
        return now - timedelta(days=30)
    return None


def answer_question(store: VectorStore, question: str, top_k: int = 5) -> dict[str, object]:
    source_types = infer_source_types(question)
    since = infer_since(question)
    retrieval_query = expand_query(question)
    results = store.search(retrieval_query, top_k=top_k, source_types=source_types, since=since)
    answer = synthesize_answer(question, results)
    return {
        "question": question,
        "answer": answer,
        "filters": {
            "source_types": source_types,
            "since": since.isoformat() if since else None,
        },
        "contexts": [
            {
                "id": item.document.id,
                "score": round(item.score, 4),
                "source_type": item.document.source_type,
                "source_name": item.document.source_name,
                "title": item.document.title,
                "published_at": item.document.published_at.isoformat(),
                "url": item.document.url,
                "snippet": item.document.content[:420],
                "metadata": item.document.metadata,
            }
            for item in results
        ],
    }


def synthesize_answer(question: str, results: list[SearchResult]) -> str:
    if not results:
        return "未检索到足够相关的近期待证据。建议放宽时间范围或补充数据源后重试。"
    bullets: list[str] = []
    for result in results[:5]:
        doc = result.document
        sentence = _best_sentence(question, doc.content) or doc.summary or doc.title
        date = doc.published_at.date().isoformat()
        bullets.append(f"- {date} [{doc.source_type}/{doc.source_name}] {sentence}")
    prefix = "基于当前向量库中检索到的证据，结论如下："
    suffix = "以上回答仅使用返回的检索上下文生成；如上下文包含 synthetic 样本，应仅作为开发联调参考。"
    return "\n".join([prefix, *bullets, suffix])


def _best_sentence(question: str, content: str) -> str:
    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", question.lower()))
    best = ""
    best_score = -1
    for sentence in sentence_split(content):
        terms = set(re.findall(r"[\w\u4e00-\u9fff]+", sentence.lower()))
        score = len(query_terms & terms)
        if score > best_score:
            best = sentence
            best_score = score
    return best[:260]
