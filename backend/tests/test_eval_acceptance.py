"""Contracts and acceptance gating for PRD evaluation and business-value data."""

import asyncio
import csv
from pathlib import Path

import pytest

from app.core.config import Settings
from app.evals.acceptance import (
    add_acceptance_gates,
    load_acceptance_cases,
)
from app.evals.annotation_import import import_job_annotation_csv
from app.evals.business_value import analyze_business_value_rows
from app.evals.datasets import JOB_PATH, RAG_PATH
from app.evals.runner import _usage_report, dataset_summary, evaluate_rag, load_jsonl
from app.evals.schemas import JobExtractionEvalCase, RAGEvalCase
from app.services.knowledge import CitationCandidate, GroundedAnswerCandidate


def _human_job_case(case_id: str = "job-case-001") -> JobExtractionEvalCase:
    return JobExtractionEvalCase.model_validate(
        {
            "id": case_id,
            "dataset_kind": "human_annotated_acceptance_v1",
            "source_reference": "https://careers.example.org/jobs/001",
            "source_captured_at": "2026-10-01",
            "source_text": (
                "示例企业招聘后端工程师，工作地点为上海，要求本科及以上学历。"
            ),
            "expected": {
                "company_name": "示例企业",
                "title": "后端工程师",
                "city": "上海",
                "job_type": None,
                "batch": None,
                "deadline": None,
                "education_requirement": "本科及以上",
                "required_skills": [],
            },
            "annotation": {
                "annotation_id": f"{case_id}-v1",
                "annotator_id": "A001",
                "annotated_at": "2026-10-02T09:30:00+08:00",
            },
        }
    )


class FakeEmbeddingProvider:
    async def embed(self, texts: list[str], settings: Settings):
        return [[1.0, 0.0] for _ in texts], "test-embedding-model"


class FakeAnswerProvider:
    async def answer(self, question: str, chunks, settings: Settings):
        source = chunks[0]
        return GroundedAnswerCandidate(
            answer="示例企业研发中心位于上海。",
            citations=[CitationCandidate(chunk_id=source.id, quote=source.content)],
        )


class EmptySearchProvider:
    async def search(self, query: str, count: int, settings: Settings):
        return []


def test_acceptance_schemas_require_auditable_anonymous_annotations() -> None:
    valid = _human_job_case()
    assert valid.annotation is not None

    incomplete = valid.model_dump(mode="json")
    incomplete["annotation"]["annotated_at"] = "2026-10-02T09:30:00"
    with pytest.raises(ValueError):
        JobExtractionEvalCase.model_validate(incomplete)

    personal_id = valid.model_dump(mode="json")
    personal_id["annotation"]["annotator_id"] = "annotator@example.org"
    with pytest.raises(ValueError):
        JobExtractionEvalCase.model_validate(personal_id)


def test_acceptance_preflight_refuses_synthetic_data_and_small_corpora(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="synthetic smoke data"):
        load_acceptance_cases("job_extraction", JOB_PATH)

    small_path = tmp_path / "temporary-human-acceptance-test.jsonl"
    small_path.write_text(_human_job_case().model_dump_json() + "\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="at least 50"):
            load_acceptance_cases("job_extraction", small_path)
    finally:
        small_path.unlink(missing_ok=True)


def test_smoke_runner_does_not_bypass_human_acceptance_gates(tmp_path: Path) -> None:
    dataset = tmp_path / "human-annotated.jsonl"
    dataset.write_text(_human_job_case().model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="app.evals.acceptance"):
        dataset_summary("job_extraction", dataset)


def test_acceptance_gates_report_critical_field_thresholds() -> None:
    report = {
        "samples": 50,
        "per_field": {
            field: {"precision": 0.9}
            for field in (
                "company_name",
                "title",
                "city",
                "deadline",
                "education_requirement",
                "required_skills",
            )
        },
    }
    result = add_acceptance_gates("job_extraction", report)
    assert result["acceptance_passed"] is True
    result["per_field"]["deadline"]["precision"] = 0.89
    assert add_acceptance_gates("job_extraction", result)["acceptance_passed"] is False


def test_job_annotation_csv_import_validates_rows_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "annotations.csv"
    output = tmp_path / "nested" / "acceptance.jsonl"
    columns = [
        "id",
        "source_reference",
        "source_captured_at",
        "source_text",
        "company_name",
        "title",
        "city",
        "job_type",
        "batch",
        "deadline",
        "education_requirement",
        "required_skills_json",
        "annotator_id",
        "annotated_at",
        "reviewer_id",
    ]
    row = {
        "id": "job-case-002",
        "source_reference": "https://careers.example.org/jobs/002",
        "source_captured_at": "2026-10-01",
        "source_text": (
            "另一示例企业招聘数据工程师，工作地点为杭州，要求本科及以上学历。"
        ),
        "company_name": "另一示例企业",
        "title": "数据工程师",
        "city": "杭州",
        "job_type": "全职",
        "batch": "秋招",
        "deadline": "",
        "education_requirement": "本科及以上",
        "required_skills_json": '["Python", "SQL"]',
        "annotator_id": "A001",
        "annotated_at": "2026-10-02T09:30:00+08:00",
        "reviewer_id": "",
    }
    with source.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)

    assert import_job_annotation_csv(source, output)["rows_imported"] == 1
    imported = load_jsonl(output, JobExtractionEvalCase)[0]
    assert imported.expected.required_skills == ["Python", "SQL"]

    row["required_skills_json"] = "not-json"
    with source.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)
    with pytest.raises(ValueError, match="invalid"):
        import_job_annotation_csv(source, output)
    assert len(load_jsonl(output, JobExtractionEvalCase)) == 1


def test_rag_acceptance_schema_requires_category_consistent_labels() -> None:
    case = load_jsonl(RAG_PATH, RAGEvalCase)[0].model_dump(mode="json")
    case["category"] = "no_answer"
    with pytest.raises(ValueError, match="category and expected_mode"):
        RAGEvalCase.model_validate(case)

    case = load_jsonl(RAG_PATH, RAGEvalCase)[0].model_dump(mode="json")
    case["dataset_kind"] = "human_annotated_acceptance_v1"
    case["as_of_date"] = "2026-10-02"
    case["annotation"] = {
        "annotation_id": "rag-case-001-v1",
        "annotator_id": "A001",
        "annotated_at": "2026-10-02T09:30:00+08:00",
    }
    case["documents"][0]["source_reference"] = None
    case["documents"][0]["source_captured_at"] = None
    with pytest.raises(ValueError, match="source reference and capture date"):
        RAGEvalCase.model_validate(case)


def test_stale_rag_sources_are_not_counted_as_current_fact_support() -> None:
    stale_case = {
        "id": "rag-stale-001",
        "dataset_kind": "human_annotated_acceptance_v1",
        "category": "stale",
        "question": "该企业目前使用什么技术栈？",
        "as_of_date": "2026-10-01",
        "documents": [
            {
                "id": "aa149fc2-7ef8-4c41-8c4c-7467af0e673c",
                "text": "企业在 2022 年时使用 Java 8。",
                "relevant": False,
                "source_reference": "https://example.org/old-source",
                "source_captured_at": "2022-01-01",
            }
        ],
        "expected_mode": "insufficient",
        "annotation": {
            "annotation_id": "rag-stale-001-v1",
            "annotator_id": "A001",
            "annotated_at": "2026-10-02T09:30:00+08:00",
        },
    }
    RAGEvalCase.model_validate(stale_case)

    stale_case["documents"][0]["relevant"] = True
    with pytest.raises(ValueError, match="cannot support a current factual answer"):
        RAGEvalCase.model_validate(stale_case)


def test_rag_factual_support_is_separate_from_quote_validity() -> None:
    case = load_jsonl(RAG_PATH, RAGEvalCase)[0]
    relevant_id = next(document.id for document in case.documents if document.relevant)
    irrelevant_id = next(document.id for document in case.documents if not document.relevant)
    from app.evals.metrics import score_rag_case

    score = score_rag_case(
        case,
        retrieved_ids=[relevant_id, irrelevant_id],
        answer="示例回答。",
        generated_citations=[relevant_id, irrelevant_id],
        supported_citations=[relevant_id, irrelevant_id],
    )
    assert score["supported_citation_count"] == 2
    assert score["fact_supported_citation_count"] == 1


def test_rag_evaluation_reports_search_success_even_for_empty_valid_result() -> None:
    case = next(
        case
        for case in load_jsonl(RAG_PATH, RAGEvalCase)
        if case.category == "answer" and case.id == "rag-smoke-001"
    )
    settings = Settings(_env_file=None, environment="test")
    report = asyncio.run(
        evaluate_rag(
            [case],
            settings=settings,
            embedding_provider=FakeEmbeddingProvider(),
            answer_provider=FakeAnswerProvider(),
            search_provider=EmptySearchProvider(),
        )
    )
    assert report["search_tool"]["success_rate"] == 1.0
    assert report["search_tool"]["nonempty_result_rate"] == 0.0


def test_provider_usage_does_not_claim_complete_cost_after_failed_calls() -> None:
    token_usage, cost_estimate = _usage_report(
        [
            {
                "calls": [
                    {
                        "operation": "web_search",
                        "outcome": "http_error",
                        "estimated_cost_usd": 0.01,
                    }
                ]
            }
        ]
    )
    assert token_usage is not None
    assert token_usage["model_calls"] == 0
    assert cost_estimate == {
        "provider_calls": 1,
        "estimated_usd": None,
        "failed_provider_calls": 1,
        "complete": False,
    }


def test_business_value_analysis_reports_paired_change_and_deadlines() -> None:
    rows = [
        {
            "participant_id": "P001",
            "phase": "baseline",
            "week_start": "2026-10-05",
            "observation_days": "7",
            "job_organization_minutes": "60",
            "status_maintenance_minutes": "20",
            "company_research_minutes": "40",
            "deadlines_due": "2",
            "missed_deadlines": "1",
        },
        {
            "participant_id": "P001",
            "phase": "with_agent",
            "week_start": "2026-10-12",
            "observation_days": "7",
            "job_organization_minutes": "30",
            "status_maintenance_minutes": "10",
            "company_research_minutes": "20",
            "deadlines_due": "3",
            "missed_deadlines": "0",
        },
    ]
    report = analyze_business_value_rows(rows)
    assert report["paired_participants"] == 1
    assert report["observation_rows"] == 2
    assert report["unique_calendar_weeks"] == 2
    assert report["paired_change"]["mean_weekly_minutes_saved"] == 60.0
    assert report["phase_summaries"]["baseline"]["missed_deadline_rate"] == 0.5
    assert "do not establish" in report["interpretation"]


@pytest.mark.parametrize(
    "participant_id,week_start",
    [("person@example.org", "2026-10-05"), ("P001", "2026-10-06")],
)
def test_business_value_rejects_identifying_codes_and_non_monday_weeks(
    participant_id: str, week_start: str
) -> None:
    row = {
        "participant_id": participant_id,
        "phase": "baseline",
        "week_start": week_start,
        "observation_days": "7",
        "job_organization_minutes": "10",
        "status_maintenance_minutes": "10",
        "company_research_minutes": "10",
        "deadlines_due": "0",
        "missed_deadlines": "0",
    }
    with pytest.raises(ValueError):
        analyze_business_value_rows([row])
