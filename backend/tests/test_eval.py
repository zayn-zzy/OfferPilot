"""CPU-only contracts and scoring tests for synthetic Agent evaluation data."""

import asyncio

from app.core.config import Settings
from app.evals.datasets import JOB_PATH, RAG_PATH
from app.evals.metrics import score_job_extraction, score_rag_case
from app.evals.runner import (
    dataset_summary,
    evaluate_job_extraction,
    evaluate_rag,
    load_jsonl,
)
from app.evals.schemas import JobExtractionEvalCase, RAGEvalCase
from app.services.job_extraction import JobExtractionCandidate
from app.services.knowledge import CitationCandidate, GroundedAnswerCandidate


class FakeExtractionProvider:
    def __init__(self, expected: dict[str, object]) -> None:
        self.expected = expected

    async def extract(self, source_text: str, settings: Settings):
        values = {}
        for field, value in self.expected.items():
            evidence = source_text[:20] if value not in (None, []) else None
            values[field] = {"value": value, "confidence": 0.99 if evidence else 0, "evidence": evidence}
        return JobExtractionCandidate.model_validate(values), "fake-eval-model"


class FakeEmbeddingProvider:
    async def embed(self, texts: list[str], settings: Settings):
        vectors = [
            [1.0, 0.0] if "演示企业01" in text else [0.0, 1.0]
            for text in texts
        ]
        return vectors, "fake-embedding-model"


class FakeAnswerProvider:
    async def answer(self, question: str, chunks, settings: Settings):
        source = chunks[0]
        return GroundedAnswerCandidate(
            answer="演示企业01的研发中心位于样例城市01。",
            citations=[CitationCandidate(chunk_id=source.id, quote=source.content)],
        )


def test_smoke_datasets_have_expected_size_and_case_mix() -> None:
    jobs = load_jsonl(JOB_PATH, JobExtractionEvalCase)
    rag_cases = load_jsonl(RAG_PATH, RAGEvalCase)

    assert len(jobs) == 50
    assert len(rag_cases) == 30
    assert {case.dataset_kind for case in jobs + rag_cases} == {"synthetic_smoke_v1"}
    assert {case.category for case in rag_cases} == {
        "answer",
        "conflict",
        "stale",
        "no_answer",
    }
    assert sum(case.security_probe for case in rag_cases) == 4
    assert dataset_summary("job_extraction", JOB_PATH)["live_provider_calls"] is False
    assert dataset_summary("rag_company_research", RAG_PATH)["security_probes"] == 4


def test_job_extraction_metrics_score_exact_fields_and_source_evidence() -> None:
    cases = load_jsonl(JOB_PATH, JobExtractionEvalCase)[:2]
    predictions = {}
    for case in cases:
        predictions[case.id] = {
            "fields": {
                field: {
                    "value": getattr(case.expected, field),
                    "evidence": case.source_text[:20],
                }
                for field in (
                    "company_name",
                    "title",
                    "city",
                    "job_type",
                    "batch",
                    "deadline",
                    "education_requirement",
                    "required_skills",
                )
            }
        }
    predictions[cases[1].id]["fields"]["city"]["evidence"] = "不存在于原文的城市依据"

    report = score_job_extraction(
        cases,
        predictions,
        {case.id: 1.0 for case in cases},
        {},
        "smoke-model",
    )

    assert report["samples"] == 2
    assert report["exact_accuracy"] == 1.0
    assert report["citation_support_rate"] < 1.0
    assert report["latency_seconds"] == {"p50": 1.0, "p95": 1.0}
    assert report["token_usage"] is None
    assert report["cost_estimate"] is None


def test_rag_metrics_check_conflict_and_abstention_behavior() -> None:
    cases = load_jsonl(RAG_PATH, RAGEvalCase)
    conflict = next(case for case in cases if case.category == "conflict")
    abstention = next(case for case in cases if case.category == "no_answer")

    conflict_ids = list(conflict.relevant_source_ids)
    conflict_score = score_rag_case(
        conflict,
        retrieved_ids=conflict_ids,
        answer="不同来源对办公地点的信息存在冲突。",
        generated_citations=conflict_ids,
        supported_citations=conflict_ids,
    )
    abstention_score = score_rag_case(
        abstention,
        retrieved_ids=[document.id for document in abstention.documents],
        answer="资料中没有找到能够回答这个问题的依据。",
        generated_citations=[],
        supported_citations=[],
    )

    assert conflict_score["mode_correct"] is True
    assert conflict_score["retrieval_recall_at_k"] == 1.0
    assert abstention_score["mode_correct"] is True
    assert abstention_score["retrieval_recall_at_k"] is None


def test_live_evaluator_paths_accept_injected_fake_providers() -> None:
    settings = Settings(_env_file=None, environment="test")
    job_case = load_jsonl(JOB_PATH, JobExtractionEvalCase)[1]
    job_report = asyncio.run(
        evaluate_job_extraction(
            [job_case],
            settings=settings,
            provider=FakeExtractionProvider(job_case.expected.model_dump()),
        )
    )
    rag_case = next(
        case
        for case in load_jsonl(RAG_PATH, RAGEvalCase)
        if case.category == "answer" and case.id == "rag-smoke-001"
    )
    rag_report = asyncio.run(
        evaluate_rag(
            [rag_case],
            settings=settings,
            embedding_provider=FakeEmbeddingProvider(),
            answer_provider=FakeAnswerProvider(),
        )
    )

    assert job_report["success_rate"] == 1.0
    assert job_report["exact_accuracy"] == 1.0
    assert rag_report["mode_accuracy"] == 1.0
    assert rag_report["retrieval_recall_at_5"] == 1.0
