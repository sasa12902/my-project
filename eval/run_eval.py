from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean
from typing import Any

from pipeline.qa import answer_question
from pipeline.storage import DEFAULT_DB_PATH, VectorStore

GROUND_TRUTH_PATH = Path(__file__).with_name("ground_truth.jsonl")


def load_cases(path: Path = GROUND_TRUTH_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def recall_at_5(response: dict[str, Any], expected_source_types: list[str], must_contain_any: list[str]) -> float:
    contexts = response["contexts"][:5]
    if not contexts:
        return 0.0
    source_hit = any(ctx["source_type"] in expected_source_types for ctx in contexts)
    haystack = " ".join(f"{ctx['title']} {ctx['snippet']} {ctx['source_name']}" for ctx in contexts).lower()
    keyword_hit = any(keyword.lower() in haystack for keyword in must_contain_any)
    return 1.0 if source_hit and keyword_hit else 0.0


def answer_faithfulness(response: dict[str, Any]) -> float:
    answer = response["answer"].lower()
    contexts = response["contexts"]
    if not contexts:
        return 0.0
    context_terms = set(re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]{2,}", " ".join(ctx["snippet"].lower() for ctx in contexts)))
    answer_terms = set(re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]{2,}", answer))
    answer_terms = {term for term in answer_terms if len(term) > 1}
    if not answer_terms:
        return 0.0
    overlap = len(answer_terms & context_terms) / len(answer_terms)
    citation_like = answer.count("[") >= min(1, len(contexts))
    return min(1.0, overlap + (0.1 if citation_like else 0.0))


def main() -> None:
    store = VectorStore(DEFAULT_DB_PATH)
    cases = load_cases()
    rows = []
    for case in cases:
        response = answer_question(store, case["question"], top_k=5)
        recall = recall_at_5(response, case["expected_source_types"], case["must_contain_any"])
        faithfulness = answer_faithfulness(response)
        rows.append(
            {
                "id": case["id"],
                "recall@5": recall,
                "faithfulness": faithfulness,
                "contexts": len(response["contexts"]),
            }
        )
    print(json.dumps({"summary": summarize(rows), "rows": rows}, ensure_ascii=False, indent=2))


def summarize(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"recall@5": 0.0, "faithfulness": 0.0}
    return {
        "recall@5": round(mean(row["recall@5"] for row in rows), 4),
        "faithfulness": round(mean(row["faithfulness"] for row in rows), 4),
    }


if __name__ == "__main__":
    main()
