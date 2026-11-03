"""Descriptive before/after analysis for PRD business-value observations."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any

PHASES = {"baseline", "with_agent"}
TIME_FIELDS = (
    "job_organization_minutes",
    "status_maintenance_minutes",
    "company_research_minutes",
)
REQUIRED_FIELDS = (
    "participant_id",
    "phase",
    "week_start",
    "observation_days",
    *TIME_FIELDS,
    "deadlines_due",
    "missed_deadlines",
)


def analyze_business_value_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Summarize paired self-reported observations without causal claims."""

    if not rows:
        raise ValueError("No business-value observations were provided.")

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    participant_phases: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {phase: [] for phase in PHASES}
    )
    for line_number, row in enumerate(rows, start=2):
        missing = set(REQUIRED_FIELDS) - set(row)
        if missing:
            raise ValueError(f"Row {line_number} is missing columns: {', '.join(sorted(missing))}")
        participant_id = row["participant_id"].strip().upper()
        if not re.fullmatch(r"P[0-9]{3,8}", participant_id, flags=re.IGNORECASE):
            raise ValueError(
                f"Row {line_number} participant_id must be an anonymous code such as P001."
            )
        phase = row["phase"].strip()
        if phase not in PHASES:
            raise ValueError(f"Row {line_number} phase must be baseline or with_agent.")
        try:
            week_start = date.fromisoformat(row["week_start"].strip())
            observation_days = int(row["observation_days"])
            values = {field: float(row[field]) for field in TIME_FIELDS}
            deadlines_due = int(row["deadlines_due"])
            missed_deadlines = int(row["missed_deadlines"])
        except (TypeError, ValueError):
            raise ValueError(
                f"Row {line_number} contains an invalid date or numeric value."
            ) from None
        if not 1 <= observation_days <= 7:
            raise ValueError(f"Row {line_number} observation_days must be between 1 and 7.")
        if week_start.weekday() != 0:
            raise ValueError(f"Row {line_number} week_start must be a Monday (ISO week start).")
        if any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError(f"Row {line_number} time values must be finite and nonnegative.")
        if deadlines_due < 0 or not 0 <= missed_deadlines <= deadlines_due:
            raise ValueError(f"Row {line_number} missed_deadlines must be within deadlines_due.")
        key = (participant_id, phase, week_start.isoformat())
        if key in seen:
            raise ValueError(f"Duplicate participant/phase/week observation at row {line_number}.")
        seen.add(key)
        weekly_minutes = sum(values.values()) * 7 / observation_days
        normalized_row = {
            "participant_id": participant_id,
            "phase": phase,
            "week_start": week_start,
            "observation_days": observation_days,
            **values,
            "weekly_minutes": weekly_minutes,
            "deadlines_due": deadlines_due,
            "missed_deadlines": missed_deadlines,
        }
        participant_phases[participant_id][phase].append(normalized_row)
        normalized.append(normalized_row)

    unpaired = [
        participant_id
        for participant_id, phases in participant_phases.items()
        if not phases["baseline"] or not phases["with_agent"]
    ]
    if unpaired:
        raise ValueError(
            "Every participant must have both baseline and with_agent observations; "
            f"unpaired codes: {', '.join(sorted(unpaired))}."
        )

    for participant_id, phases in participant_phases.items():
        last_baseline_week = max(row["week_start"] for row in phases["baseline"])
        first_agent_week = min(row["week_start"] for row in phases["with_agent"])
        if last_baseline_week >= first_agent_week:
            raise ValueError(
                "Baseline observations must end before with_agent observations begin; "
                f"participant {participant_id} has overlapping or reversed phases."
            )

    participant_summaries: list[dict[str, Any]] = []
    for participant_id, phases in sorted(participant_phases.items()):
        baseline_weeks = phases["baseline"]
        agent_weeks = phases["with_agent"]
        baseline_minutes = mean(row["weekly_minutes"] for row in baseline_weeks)
        agent_minutes = mean(row["weekly_minutes"] for row in agent_weeks)
        saved = baseline_minutes - agent_minutes
        participant_summaries.append(
            {
                "participant_id": participant_id,
                "baseline_weekly_minutes": round(baseline_minutes, 2),
                "with_agent_weekly_minutes": round(agent_minutes, 2),
                "weekly_minutes_saved": round(saved, 2),
                "weekly_time_reduction_rate": round(saved / baseline_minutes, 4)
                if baseline_minutes
                else None,
            }
        )

    phase_summaries: dict[str, dict[str, Any]] = {}
    for phase in sorted(PHASES):
        phase_rows = [row for row in normalized if row["phase"] == phase]
        participant_component_means = {
            field: [
                mean(
                    row[field] * 7 / row["observation_days"]
                    for row in participant_phases[participant_id][phase]
                )
                for participant_id in participant_phases
            ]
            for field in TIME_FIELDS
        }
        due = sum(row["deadlines_due"] for row in phase_rows)
        missed = sum(row["missed_deadlines"] for row in phase_rows)
        phase_summaries[phase] = {
            "participants": len(participant_phases),
            "weeks": len(phase_rows),
            "observation_days": sum(row["observation_days"] for row in phase_rows),
            "weekly_minutes_per_participant_mean": round(
                mean(
                    mean(
                        row["weekly_minutes"]
                        for row in participant_phases[participant_id][phase]
                    )
                    for participant_id in participant_phases
                ),
                2,
            ),
            "weekly_minutes_per_participant_median": round(
                median(
                    mean(
                        row["weekly_minutes"]
                        for row in participant_phases[participant_id][phase]
                    )
                    for participant_id in participant_phases
                ),
                2,
            ),
            "weekly_task_minutes_per_participant_mean": {
                field: round(mean(values), 2)
                for field, values in participant_component_means.items()
            },
            "deadlines_due": due,
            "missed_deadlines": missed,
            "missed_deadline_rate": round(missed / due, 4) if due else None,
            "period_start": min(row["week_start"] for row in phase_rows).isoformat(),
            "period_end": max(row["week_start"] for row in phase_rows).isoformat(),
        }

    saved_minutes = [row["weekly_minutes_saved"] for row in participant_summaries]
    reduction_rates = [
        row["weekly_time_reduction_rate"]
        for row in participant_summaries
        if row["weekly_time_reduction_rate"] is not None
    ]
    return {
        "report_kind": "self_reported_before_after_descriptive_v1",
        "paired_participants": len(participant_summaries),
        "observation_rows": len(normalized),
        "unique_calendar_weeks": len({row["week_start"] for row in normalized}),
        "period_start": min(row["week_start"] for row in normalized).isoformat(),
        "period_end": max(row["week_start"] for row in normalized).isoformat(),
        "phase_summaries": phase_summaries,
        "paired_change": {
            "mean_weekly_minutes_saved": round(mean(saved_minutes), 2),
            "median_weekly_minutes_saved": round(median(saved_minutes), 2),
            "median_weekly_time_reduction_rate": round(median(reduction_rates), 4)
            if reduction_rates
            else None,
            "participants_with_time_reduction": sum(value > 0 for value in saved_minutes),
            "participants_with_no_reduction": sum(value == 0 for value in saved_minutes),
            "participants_with_more_time_after": sum(value < 0 for value in saved_minutes),
        },
        "participant_pairs": participant_summaries,
        "interpretation": (
            "Descriptive self-reported before/after observations; they do not establish "
            "that OfferPilot caused the change or generalize to other job seekers."
        ),
        "limitations": [
            "Observations are self-reported and may be affected by recall or selection bias.",
            "A single person's experience must not be generalized to all job seekers.",
            (
                "Partial weeks are scaled linearly to seven days; this assumes activity "
                "is evenly distributed across observed days."
            ),
        ],
        "personal_data_policy": (
            "Use anonymous participant codes. Do not put names, emails, phone numbers, "
            "resumes, or job-posting text in this measurement file."
        ),
    }


def read_business_value_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or set(REQUIRED_FIELDS) - set(reader.fieldnames):
            raise ValueError("Business-value CSV does not contain the required header fields.")
        return list(reader)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize anonymous weekly before/after observations."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze_business_value_rows(read_business_value_csv(args.input))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
