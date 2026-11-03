"""Convert a human-completed job annotation spreadsheet to evaluator JSONL."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from app.evals.schemas import JobExtractionEvalCase

JOB_ANNOTATION_COLUMNS = (
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
)


def import_job_annotation_csv(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Validate all spreadsheet rows before writing a machine-readable corpus."""

    with input_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or set(JOB_ANNOTATION_COLUMNS) - set(reader.fieldnames):
            raise ValueError("Job annotation CSV is missing required columns.")
        rows = list(reader)
    if not rows:
        raise ValueError("Job annotation CSV must contain at least one labeled row.")

    cases = []
    for line_number, row in enumerate(rows, start=2):
        try:
            skills = json.loads(row["required_skills_json"] or "[]")
            if not isinstance(skills, list) or any(not isinstance(skill, str) for skill in skills):
                raise ValueError("required_skills_json must be a JSON string array")
            expected = {
                field: (row[field].strip() or None)
                for field in (
                    "company_name",
                    "title",
                    "city",
                    "job_type",
                    "batch",
                    "deadline",
                    "education_requirement",
                )
            }
            expected["required_skills"] = skills
            annotation = {
                "annotation_id": row["id"].strip(),
                "annotator_id": row["annotator_id"].strip(),
                "annotated_at": row["annotated_at"].strip(),
            }
            reviewer_id = row.get("reviewer_id", "").strip()
            if reviewer_id:
                annotation["reviewer_id"] = reviewer_id
            case = JobExtractionEvalCase.model_validate(
                {
                    "id": row["id"].strip(),
                    "dataset_kind": "human_annotated_acceptance_v1",
                    "source_reference": row["source_reference"].strip(),
                    "source_captured_at": row["source_captured_at"].strip(),
                    "source_text": row["source_text"],
                    "expected": expected,
                    "annotation": annotation,
                }
            )
        except Exception as exc:
            raise ValueError(
                f"{input_path}:{line_number} is invalid ({type(exc).__name__})."
            ) from None
        cases.append(case)

    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Job annotation CSV contains duplicate case IDs.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(case.model_dump_json() + "\n" for case in cases),
        encoding="utf-8",
    )
    return {"rows_imported": len(cases), "output": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import manually annotated job-extraction CSV rows."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = import_job_annotation_csv(args.input, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
