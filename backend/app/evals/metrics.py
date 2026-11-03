"""Deterministic scoring helpers for job extraction and grounded RAG runs."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any
from uuid import UUID

from app.evals.schemas import JobExtractionEvalCase, RAGEvalCase

EXTRACTION_FIELDS = (
    "company_name",
    "title",
    "city",
    "job_type",
    "batch",
    "deadline",
    "education_requirement",
    "required_skills",
)
ABSTENTION_MARKERS = ("资料中没有找到", "没有找到", "证据不足", "无法确定", "无法判断", "未提供")
CONFLICT_MARKERS = ("存在冲突", "信息冲突", "不同来源", "不一致", "相互矛盾")


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return tuple(sorted({_normalize(item) for item in value if item is not None}))
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value).strip().casefold()
        return normalized or None
    return value


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def score_job_extraction(
    cases: list[JobExtractionEvalCase],
    predictions: dict[str, dict[str, Any]],
    latencies: dict[str, float],
    errors: dict[str, str],
    model_name: str | None,
) -> dict[str, Any]:
    per_field: dict[str, dict[str, float | int]] = {}
    totals = Counter(tp=0, fp=0, fn=0, exact=0, fields=0)
    evidence_checked = 0
    evidence_supported = 0

    for field in EXTRACTION_FIELDS:
        tp = fp = fn = exact = count = 0
        for case in cases:
            expected = getattr(case.expected, field)
            prediction = predictions.get(case.id, {}).get("fields", {}).get(field, {})
            actual = prediction.get("value")
            is_exact = _normalize(expected) == _normalize(actual)
            count += 1
            exact += int(is_exact)
            expected_present = _normalize(expected) not in (None, ())
            actual_present = _normalize(actual) not in (None, ())
            tp += int(expected_present and is_exact)
            fp += int(actual_present and not is_exact)
            fn += int(expected_present and not is_exact)
            if actual_present:
                evidence_checked += 1
                evidence = prediction.get("evidence")
                source_text = case.source_text
                evidence_supported += int(
                    isinstance(evidence, str) and bool(evidence) and evidence in source_text
                )

        per_field[field] = {
            "exact_accuracy": round(exact / count, 4) if count else 0.0,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "samples": count,
        }
        totals.update(tp=tp, fp=fp, fn=fn, exact=exact, fields=count)

    successful = len(predictions)
    dataset_kind = cases[0].dataset_kind if cases else None
    limitations = []
    if dataset_kind == "synthetic_smoke_v1":
        limitations.append(
            "样本为合成烟雾集，不代表真实招聘语料或 PRD 人工标注验收集。"
        )
    if dataset_kind == "human_annotated_acceptance_v1":
        limitations.append(
            "人工标注质量与代表性仍需结合标注方案、抽样范围和错误案例审阅。"
        )
    return {
        "task": "job_extraction",
        "dataset_kind": dataset_kind,
        "model": model_name,
        "samples": len(cases),
        "successes": successful,
        "failures": len(errors),
        "success_rate": round(successful / len(cases), 4) if cases else 0.0,
        "exact_accuracy": round(totals["exact"] / totals["fields"], 4)
        if totals["fields"]
        else 0.0,
        "precision": round(totals["tp"] / (totals["tp"] + totals["fp"]), 4)
        if totals["tp"] + totals["fp"]
        else 0.0,
        "recall": round(totals["tp"] / (totals["tp"] + totals["fn"]), 4)
        if totals["tp"] + totals["fn"]
        else 0.0,
        "citation_support_rate": round(evidence_supported / evidence_checked, 4)
        if evidence_checked
        else None,
        "latency_seconds": {
            "p50": _percentile(list(latencies.values()), 0.50),
            "p95": _percentile(list(latencies.values()), 0.95),
        },
        "per_field": per_field,
        "errors": errors,
        "token_usage": None,
        "cost_estimate": None,
        "limitations": limitations,
    }


def score_rag_case(
    case: RAGEvalCase,
    *,
    retrieved_ids: list[UUID],
    answer: str,
    generated_citations: list[UUID],
    supported_citations: list[UUID],
    k: int = 5,
) -> dict[str, Any]:
    relevant = case.relevant_source_ids
    top_ids = retrieved_ids[:k]
    recall = len(relevant.intersection(top_ids)) / len(relevant) if relevant else None
    citation_set = set(supported_citations)
    if case.expected_mode == "conflict":
        detected_mode = (
            "conflict"
            if len(relevant.intersection(citation_set)) >= 2
            and any(marker in answer for marker in CONFLICT_MARKERS)
            else "insufficient"
        )
    elif case.expected_mode == "insufficient":
        detected_mode = (
            "insufficient"
            if not generated_citations
            and any(marker in answer for marker in ABSTENTION_MARKERS)
            else "answer"
        )
    else:
        has_relevant_support = bool(relevant.intersection(citation_set))
        detected_mode = "answer" if has_relevant_support else "insufficient"

    return {
        "id": case.id,
        "category": case.category,
        "expected_mode": case.expected_mode,
        "detected_mode": detected_mode,
        "mode_correct": detected_mode == case.expected_mode,
        "retrieval_recall_at_k": recall,
        "k": k,
        "expected_source_count": len(relevant),
        "retrieved_source_count": len(top_ids),
        "supported_citation_count": len(supported_citations),
        "fact_supported_citation_count": sum(
            citation_id in relevant for citation_id in supported_citations
        ),
        "generated_citation_count": len(generated_citations),
        "conflict_sources_covered": len(relevant.intersection(citation_set)),
    }


def summarize_rag_scores(
    cases: list[RAGEvalCase],
    scores: list[dict[str, Any]],
    latencies: dict[str, float],
    errors: dict[str, str],
    *,
    embedding_model: str | None,
    answer_model: str | None,
) -> dict[str, Any]:
    relevant_scores = [
        score["retrieval_recall_at_k"]
        for score in scores
        if score["retrieval_recall_at_k"] is not None
    ]
    generated = sum(score["generated_citation_count"] for score in scores)
    quote_valid = sum(score["supported_citation_count"] for score in scores)
    fact_supported = sum(score["fact_supported_citation_count"] for score in scores)
    category_rows: dict[str, dict[str, float | int]] = {}
    categories = sorted({case.category for case in cases})
    score_by_category: dict[str, list[dict[str, Any]]] = {
        category: [score for score in scores if score["category"] == category]
        for category in categories
    }
    for category, rows in score_by_category.items():
        category_rows[category] = {
            "samples": len(rows),
            "mode_accuracy": round(
                sum(bool(row["mode_correct"]) for row in rows) / len(rows), 4
            )
            if rows
            else 0.0,
        }
    security_case_ids = {case.id for case in cases if case.security_probe}
    security_scores = [score for score in scores if score["id"] in security_case_ids]

    dataset_kind = cases[0].dataset_kind if cases else None
    limitations = [
        (
            "冲突/弃答分类依赖可解释的中文标记词，应与人工标注的事实支持指标一起审阅。"
        ),
        "引用支持率按标注相关来源 ID 计算；逐字引用正确率单独报告。",
    ]
    if dataset_kind == "synthetic_smoke_v1":
        limitations.insert(0, "样本为合成烟雾集，不代表真实问题的人工标注验收集。")
    if dataset_kind == "human_annotated_acceptance_v1":
        limitations.append(
            "人工标注质量与代表性仍需结合标注方案、抽样范围和错误案例审阅。"
        )

    return {
        "task": "rag_company_research",
        "dataset_kind": dataset_kind,
        "embedding_model": embedding_model,
        "answer_model": answer_model,
        "samples": len(cases),
        "successes": len(scores),
        "failures": len(errors),
        "mode_accuracy": round(
            sum(bool(score["mode_correct"]) for score in scores) / len(scores), 4
        )
        if scores
        else 0.0,
        "retrieval_recall_at_5": round(sum(relevant_scores) / len(relevant_scores), 4)
        if relevant_scores
        else None,
        "citation_quote_validity_rate": round(quote_valid / generated, 4)
        if generated
        else None,
        "citation_support_rate": round(fact_supported / generated, 4)
        if generated
        else None,
        "no_answer_recognition_rate": _category_accuracy(category_rows, "no_answer"),
        "stale_abstention_rate": _category_accuracy(category_rows, "stale"),
        "conflict_detection_rate": _category_accuracy(category_rows, "conflict"),
        "latency_seconds": {
            "p50": _percentile(list(latencies.values()), 0.50),
            "p95": _percentile(list(latencies.values()), 0.95),
        },
        "per_category": category_rows,
        "security_probe": {
            "samples": len(security_case_ids),
            "safe_abstention_rate": round(
                sum(bool(score["mode_correct"]) for score in security_scores)
                / len(security_scores),
                4,
            )
            if security_scores
            else None,
        },
        "errors": errors,
        "token_usage": None,
        "cost_estimate": None,
        "limitations": limitations,
    }


def _category_accuracy(
    category_rows: dict[str, dict[str, float | int]], category: str
) -> float | None:
    row = category_rows.get(category)
    return float(row["mode_accuracy"]) if row is not None else None
