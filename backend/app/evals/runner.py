"""Opt-in live evaluator for the versioned synthetic Agent smoke datasets."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.evals.datasets import JOB_PATH, RAG_PATH
from app.evals.metrics import score_job_extraction, score_rag_case, summarize_rag_scores
from app.evals.schemas import JobExtractionEvalCase, RAGEvalCase
from app.services.job_extraction import OpenAICompatibleJobExtractionProvider
from app.services.knowledge import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerProvider,
    cosine_similarity,
    validate_answer_citations,
)

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


def load_jsonl(path: Path, model: type[Any]) -> list[Any]:
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                rows.append(model.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"{path}:{line_number} is invalid ({type(exc).__name__})") from None
    return rows


def dataset_summary(task: str, dataset_path: Path) -> dict[str, object]:
    model = JobExtractionEvalCase if task == "job_extraction" else RAGEvalCase
    cases = load_jsonl(dataset_path, model)
    kinds = sorted({case.dataset_kind for case in cases})
    if kinds != ["synthetic_smoke_v1"]:
        raise ValueError("当前 evaluator 只接受显式标记的 synthetic_smoke_v1 数据集。")
    summary: dict[str, object] = {
        "task": task,
        "dataset_kind": kinds[0],
        "samples": len(cases),
        "dataset": str(dataset_path),
        "live_provider_calls": False,
    }
    if task == "rag_company_research":
        summary["categories"] = {
            category: sum(case.category == category for case in cases)
            for category in ("answer", "conflict", "stale", "no_answer")
        }
        summary["security_probes"] = sum(case.security_probe for case in cases)
    return summary


async def evaluate_job_extraction(
    cases: list[JobExtractionEvalCase],
    *,
    settings: Settings | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = provider or OpenAICompatibleJobExtractionProvider()
    predictions: dict[str, dict[str, Any]] = {}
    latencies: dict[str, float] = {}
    errors: dict[str, str] = {}
    model_name: str | None = None
    records = []

    for case in cases:
        started = time.perf_counter()
        try:
            candidate, model_name = await provider.extract(case.source_text, settings)
            fields = {
                field: {
                    "value": getattr(candidate, field).value,
                    "evidence": getattr(candidate, field).evidence,
                    "confidence": getattr(candidate, field).confidence,
                }
                for field in EXTRACTION_FIELDS
            }
            predictions[case.id] = {"fields": fields}
            latencies[case.id] = time.perf_counter() - started
            records.append({"id": case.id, "fields": fields, "latency_seconds": latencies[case.id]})
        except Exception as exc:
            latencies[case.id] = time.perf_counter() - started
            code = getattr(exc, "code", type(exc).__name__)
            errors[case.id] = str(code)
            records.append({"id": case.id, "error_code": str(code), "latency_seconds": latencies[case.id]})

    report = score_job_extraction(cases, predictions, latencies, errors, model_name)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["records"] = records
    return report


async def evaluate_rag(
    cases: list[RAGEvalCase],
    *,
    settings: Settings | None = None,
    embedding_provider: Any | None = None,
    answer_provider: Any | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    embedding_provider = embedding_provider or OpenAICompatibleEmbeddingProvider()
    answer_provider = answer_provider or OpenAICompatibleKnowledgeAnswerProvider()
    scores = []
    latencies: dict[str, float] = {}
    errors: dict[str, str] = {}
    records = []
    embedding_model: str | None = None
    answer_model = settings.llm_model.strip() or None

    for case in cases:
        started = time.perf_counter()
        try:
            input_texts = [case.question, *(document.text for document in case.documents)]
            vectors, embedding_model = await embedding_provider.embed(input_texts, settings)
            query_vector, document_vectors = vectors[0], vectors[1:]
            ranked = sorted(
                zip(case.documents, document_vectors, strict=True),
                key=lambda pair: (cosine_similarity(query_vector, pair[1]), str(pair[0].id)),
                reverse=True,
            )
            retrieval = [
                (document, cosine_similarity(query_vector, vector))
                for document, vector in ranked[:5]
            ]
            chunks = [
                SimpleNamespace(
                    id=document.id,
                    content=document.text,
                    source_name=f"synthetic:{case.id}",
                )
                for document, _ in retrieval
            ]
            candidate = await answer_provider.answer(case.question, chunks, settings)
            answer_text, valid_citations = validate_answer_citations(
                candidate,
                [
                    (chunk, score)
                    for chunk, (_, score) in zip(chunks, retrieval, strict=True)
                ],
            )
            generated_ids = [citation.chunk_id for citation in candidate.citations]
            supported_ids = [chunk.id for chunk, _, _ in valid_citations]
            retrieved_ids = [document.id for document, _ in retrieval]
            latency = time.perf_counter() - started
            latencies[case.id] = latency
            score = score_rag_case(
                case,
                retrieved_ids=retrieved_ids,
                answer=answer_text,
                generated_citations=generated_ids,
                supported_citations=supported_ids,
            )
            scores.append(score)
            records.append(
                {
                    **score,
                    "answer": answer_text,
                    "retrieved_ids": [str(value) for value in retrieved_ids],
                    "supported_citation_ids": [str(value) for value in supported_ids],
                    "latency_seconds": latency,
                }
            )
        except Exception as exc:
            latency = time.perf_counter() - started
            latencies[case.id] = latency
            code = getattr(exc, "code", type(exc).__name__)
            errors[case.id] = str(code)
            records.append({"id": case.id, "error_code": str(code), "latency_seconds": latency})

    report = summarize_rag_scores(
        cases,
        scores,
        latencies,
        errors,
        embedding_model=embedding_model,
        answer_model=answer_model,
    )
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["records"] = records
    return report


def _default_dataset(task: str) -> Path:
    return JOB_PATH if task == "job_extraction" else RAG_PATH


def _default_output(task: str) -> Path:
    return Path("artifacts/agent-eval") / f"{task}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or inspect OfferPilot Agent smoke evaluations.")
    parser.add_argument(
        "--task",
        required=True,
        choices=("job_extraction", "rag_company_research"),
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call configured model APIs; this can incur provider cost.",
    )
    args = parser.parse_args()
    dataset_path = args.dataset or _default_dataset(args.task)
    summary = dataset_summary(args.task, dataset_path)
    model = JobExtractionEvalCase if args.task == "job_extraction" else RAGEvalCase
    cases = load_jsonl(dataset_path, model)
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[: args.limit]
    if not args.live:
        print(json.dumps({**summary, "selected_samples": len(cases)}, ensure_ascii=False, indent=2))
        return

    if args.task == "job_extraction":
        report = asyncio.run(evaluate_job_extraction(cases))
    else:
        report = asyncio.run(evaluate_rag(cases))
    output_path = args.output or _default_output(args.task)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False, indent=2))
    print(f"Report saved: {output_path}")


if __name__ == "__main__":
    main()
