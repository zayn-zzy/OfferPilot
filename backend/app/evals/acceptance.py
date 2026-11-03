"""PRD acceptance evaluation over manually annotated datasets."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.evals.runner import evaluate_job_extraction, evaluate_rag, load_jsonl
from app.evals.schemas import JobExtractionEvalCase, RAGEvalCase
from app.services.company_research import TavilySearchProvider

MINIMUM_SAMPLES = {"job_extraction": 50, "rag_company_research": 30}
CRITICAL_JOB_FIELDS = (
    "company_name",
    "title",
    "city",
    "deadline",
    "education_requirement",
    "required_skills",
)
ACCEPTANCE_DATASET_KIND = "human_annotated_acceptance_v1"


def load_acceptance_cases(task: str, dataset: Path) -> list[Any]:
    """Load and enforce PRD dataset size, annotation, provenance, and category rules."""

    model = JobExtractionEvalCase if task == "job_extraction" else RAGEvalCase
    cases = load_jsonl(dataset, model)
    if len(cases) < MINIMUM_SAMPLES[task]:
        raise ValueError(
            f"{task} requires at least {MINIMUM_SAMPLES[task]} annotated cases; got {len(cases)}."
        )
    if {case.dataset_kind for case in cases} != {ACCEPTANCE_DATASET_KIND}:
        raise ValueError(
            f"Acceptance runs require dataset_kind={ACCEPTANCE_DATASET_KIND}; "
            "synthetic smoke data cannot be promoted to acceptance data."
        )
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Acceptance dataset contains duplicate case IDs.")
    if task == "rag_company_research":
        required_categories = {"answer", "conflict", "stale", "no_answer"}
        found_categories = {case.category for case in cases}
        missing_categories = required_categories - found_categories
        if missing_categories:
            raise ValueError(
                "RAG acceptance dataset is missing categories: "
                + ", ".join(sorted(missing_categories))
            )
    return cases


def dataset_readiness(task: str, dataset: Path, cases: list[Any]) -> dict[str, Any]:
    """Describe a validated corpus without implying that model quality passed."""

    summary: dict[str, Any] = {
        "task": task,
        "dataset": str(dataset),
        "dataset_kind": ACCEPTANCE_DATASET_KIND,
        "samples": len(cases),
        "minimum_samples": MINIMUM_SAMPLES[task],
        "dataset_ready": True,
        "model_quality_evaluated": False,
        "acceptance_passed": None,
    }
    if task == "rag_company_research":
        summary["categories"] = {
            category: sum(case.category == category for case in cases)
            for category in ("answer", "conflict", "stale", "no_answer")
        }
        summary["security_probes"] = sum(case.security_probe for case in cases)
    return summary


def add_acceptance_gates(task: str, report: dict[str, Any]) -> dict[str, Any]:
    """Apply only the numerical quality thresholds that the PRD actually defines."""

    minimum = MINIMUM_SAMPLES[task]
    gates: list[dict[str, Any]] = [
        {
            "name": "minimum_annotated_samples",
            "threshold": minimum,
            "observed": report.get("samples", 0),
            "passed": int(report.get("samples", 0)) >= minimum,
        }
    ]
    if task == "job_extraction":
        per_field = report.get("per_field", {})
        for field in CRITICAL_JOB_FIELDS:
            observed = per_field.get(field, {}).get("precision")
            gates.append(
                {
                    "name": f"precision.{field}",
                    "threshold": 0.9,
                    "observed": observed,
                    "passed": observed is not None and observed >= 0.9,
                }
            )
    else:
        observed = report.get("citation_support_rate")
        gates.append(
            {
                "name": "annotated_fact_citation_support_rate",
                "threshold": 0.9,
                "observed": observed,
                "passed": observed is not None and observed >= 0.9,
            }
        )

    report["quality_gates"] = gates
    report["acceptance_passed"] = all(gate["passed"] for gate in gates)
    report["acceptance_note"] = (
        "This result applies only to the supplied, manually annotated dataset "
        "and configured providers."
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate PRD acceptance data or run provider-backed acceptance evaluation."
    )
    parser.add_argument("--task", required=True, choices=tuple(MINIMUM_SAMPLES))
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call configured model/search providers; this can incur cost.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        cases = load_acceptance_cases(args.task, args.dataset)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    readiness = dataset_readiness(args.task, args.dataset, cases)
    if not args.live:
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return

    settings = get_settings()
    if args.task == "job_extraction":
        report = asyncio.run(evaluate_job_extraction(cases, settings=settings))
    else:
        report = asyncio.run(
            evaluate_rag(
                cases,
                settings=settings,
                search_provider=TavilySearchProvider(),
            )
        )
    report = add_acceptance_gates(args.task, report)
    report["dataset"] = str(args.dataset)
    report["dataset_readiness"] = readiness

    output = args.output
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if output is not None:
        print(f"Report saved: {output}")
    if not report["acceptance_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
