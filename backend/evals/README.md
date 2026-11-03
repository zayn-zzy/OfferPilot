# OfferPilot evaluation and acceptance

This directory separates **pipeline smoke checks** from **PRD acceptance**. The checked-in
`*_smoke_v1.jsonl` files are synthetic and reproducible; they are not evidence of real-world
quality and must never be relabeled as human acceptance data.

## 1. Smoke checks

The synthetic datasets contain 50 job extraction cases and 30 RAG/company research cases,
including answerable, conflicting, stale, no-answer, and prompt-injection examples. Inspect
their shape and category counts without making network calls:

```bash
cd backend
uv run python -m app.evals.runner --task job_extraction
uv run python -m app.evals.runner --task rag_company_research
```

To run the configured model on smoke data, explicitly add `--live`. This may incur API cost.
Live smoke reports are useful for debugging but do not count as PRD acceptance.

## 2. Job extraction acceptance data

The PRD requires at least 50 **manually labeled real job texts**. Start with
`templates/job_extraction_acceptance.csv`; it contains only a header and no invented labels.
Make one row per source posting. Record an opaque case ID, source URL/reference, capture date,
the source text, and the human-reviewed values for company, title, city, deadline, education,
and skills. `required_skills_json` must be a JSON string array such as `["Python","SQL"]`.
Use anonymized reviewer codes (`A001`, `R001`), never annotator names or contact details.
Use an ISO 8601 timestamp with timezone for `annotated_at`; use a second reviewer for any
disputed value. Blank expected fields mean the source does not provide that field.

Convert the completed CSV to versioned JSONL and check it without making provider calls:

```bash
cd backend
uv run python -m app.evals.annotation_import \
  --input evals/templates/job_extraction_acceptance.csv \
  --output evals/datasets/job_extraction_acceptance_v1.jsonl
uv run python -m app.evals.acceptance \
  --task job_extraction \
  --dataset evals/datasets/job_extraction_acceptance_v1.jsonl
```

The preflight rejects fewer than 50 rows, duplicate IDs, synthetic data, missing annotation
metadata, or missing source provenance. It reports dataset readiness only; it does not say
the model passed. After the preflight is ready, run the actual configured extraction model:

```bash
uv run python -m app.evals.acceptance \
  --task job_extraction \
  --dataset evals/datasets/job_extraction_acceptance_v1.jsonl \
  --live --output artifacts/agent-eval/job-extraction-acceptance.json
```

The six PRD-critical fields each need precision of at least 0.90. The report also includes
recall, exact accuracy, source quote support, P50/P95 latency, and per-case provider telemetry.

## 3. RAG/company research acceptance data

Create at least 30 manually annotated JSONL cases using the contract in
`app.evals.schemas.RAGEvalCase`. Every document needs a stable UUID, source text, relevance
label (`relevant` means usable to support the current answer), public source reference, and
capture date. Each case needs an opaque ID, a question,
an `as_of_date` defining when information is considered current, one of the categories
`answer`, `conflict`, `stale`, or `no_answer`, an expected mode, and timezone-aware annotation
metadata. Use `A###` for the annotator and `R###` for a distinct
second reviewer on conflicts. Category rules are checked: answerable cases need a relevant
source; conflicts need at least two; no-answer and stale cases cannot label old/unsupported
sources as current factual support; stale cases need at least one source captured before
`as_of_date`; stale and no-answer questions must be expected to abstain. The corpus should
include all four categories.

Run the corpus preflight, then the live evaluation:

```bash
cd backend
uv run python -m app.evals.acceptance \
  --task rag_company_research \
  --dataset evals/datasets/rag_company_acceptance_v1.jsonl
uv run python -m app.evals.acceptance \
  --task rag_company_research \
  --dataset evals/datasets/rag_company_acceptance_v1.jsonl \
  --live --output artifacts/agent-eval/rag-company-acceptance.json
```

The live RAG run replays the annotated source snapshot for retrieval and answer scoring and
also calls the configured Tavily search once per question to measure tool availability,
non-empty result rate, errors, and search P50/P95. Those live search results are not mixed
into the labeled snapshot score; the report makes the two measurements separate. Therefore,
search success does not by itself prove that live results were relevant or correctly cited.
The PRD citation gate is based on citations that both quote a retrieved source exactly and
point to a source manually labeled as supporting the fact. Quote validity and factual source
support are reported separately. The annotated-fact citation support gate is at least 0.90.

## 4. Usage, latency, and safety regression evidence

Reports include per-case provider calls, P50/P95 task latency, token use when the provider
returns usage metadata, and estimated cost when usage and matching rates are configured.
Unknown usage/cost stays `null`; it is never represented as zero. Set the existing LLM,
embedding, and Tavily rate configuration to make cost estimates complete. Live commands can
use paid services; preflight commands cannot.

The remaining PRD zero-tolerance checks are deterministic regression tests, run with the
backend test suite:

```bash
cd backend
uv run pytest -q tests/test_external_actions.py tests/test_reminders.py
```

The external-action tests verify that unapproved or invalidated requests do not invoke the
sender and that approved retries are idempotent. Reminder tests verify atomic delivery and
that retries do not create duplicate notifications. These are pass/fail invariants, not model
quality scores. A release acceptance summary must include both test results alongside the
human-corpus reports.

## 5. Business value study

`templates/business_value_observations.csv` contains the required header but no observations.
Collect weekly self-reported minutes for job organization, application-status maintenance,
and company research, plus the number of deadlines due and missed. For each anonymized
participant code (`P001`, `P002`, ...), collect baseline weeks before using OfferPilot and
`with_agent` weeks afterward. Use one row per participant, phase, and ISO week (Monday date).
Set `observation_days` to the number of days tracked; partial-week minutes are scaled linearly
to seven days. If no deadline fell in a week, use zero for both deadline columns. Do not put
names, emails, phone numbers, resumes, or job-posting text in this file.

After entering actual observations, create a report outside source control:

```bash
cd backend
uv run python -m app.evals.business_value \
  --input evals/templates/business_value_observations.csv \
  --output artifacts/business-value-report.json
```

The report shows paired participant count, row/week counts, observation period, weekly task
time by phase, paired time changes, missed-deadline counts/rates, and limits. It requires a
baseline and post-agent phase per participant, with non-overlapping baseline-first periods.
The report is descriptive self-report only; it does not prove causality. A single participant
is not evidence of a general effect. No business-value result exists until real observations
have been collected and supplied.

## Current acceptance status

The repository contains only synthetic smoke data and empty input templates. It does **not**
yet contain the PRD's 50 human job annotations, 30 human RAG annotations, or before/after
usage observations. Thus this change makes acceptance reproducible and prevents false claims,
but it does not claim that quality thresholds or business impact have passed. Do not commit
private or identifying study data; keep local datasets/reports out of version control.
