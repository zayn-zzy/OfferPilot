# Agent evaluation smoke datasets

These checked-in datasets are synthetic, reproducible smoke inputs. They contain
no real candidate records or copied employer postings and must not be reported as
the PRD's manually annotated acceptance corpus.

- `datasets/job_extraction_smoke_v1.jsonl`: 50 generated job-text cases, including
  deliberately missing city/deadline fields. The labels are produced by the same
  deterministic fixture builder in `app/evals/datasets.py`.
- `datasets/rag_company_smoke_v1.jsonl`: 30 questions over synthetic passages,
  split into answerable, conflicting-source, stale-source, and no-answer cases.
  Four cases include untrusted instruction text as a prompt-injection smoke probe.

Validate the dataset without calling a provider:

```bash
cd backend
uv run python -m app.evals.runner --task job_extraction
uv run python -m app.evals.runner --task rag_company_research
```

Run live evaluation only when you intentionally accept model/API usage and cost:

```bash
cd backend
uv run python -m app.evals.runner --task job_extraction --live \
  --output artifacts/agent-eval/job-extraction.json
uv run python -m app.evals.runner --task rag_company_research --live \
  --output artifacts/agent-eval/rag-company.json
```

The first command needs the Chat Completions settings. The second also needs the
Embeddings settings. Reports include exact field accuracy, precision/recall,
evidence support, retrieval recall@5, answer/conflict/abstention mode checks and
P50/P95 latency. They intentionally leave token usage and cost unset because the
current provider adapters do not expose usage metadata.

These smoke reports are for checking the evaluation pipeline and regressions.
They do not establish the PRD thresholds. Acceptance evaluation still needs a
separately curated and manually annotated 50-post job set plus 30 real RAG/research
questions, adjudication for conflicting or stale evidence, and reports from the
configured providers. Do not convert these synthetic scores into claimed product
quality metrics.
