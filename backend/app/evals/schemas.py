"""Strict data contracts for synthetic Agent evaluation cases."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DatasetKind = Literal["synthetic_smoke_v1", "human_annotated_acceptance_v1"]


class EvalAnnotation(BaseModel):
    """Auditable, privacy-safe annotation metadata for acceptance examples."""

    model_config = ConfigDict(extra="forbid")

    annotation_id: str = Field(min_length=1, max_length=80)
    annotator_id: str = Field(pattern=r"^A[0-9]{3,8}$")
    annotated_at: datetime
    reviewer_id: str | None = Field(default=None, pattern=r"^R[0-9]{3,8}$")

    @field_validator("annotated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("annotated_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_distinct_reviewer(self) -> "EvalAnnotation":
        if self.reviewer_id is not None and self.reviewer_id == self.annotator_id:
            raise ValueError("The reviewer must be different from the annotator")
        return self


class ExtractionExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str | None
    title: str | None
    city: str | None
    job_type: str | None
    batch: str | None
    deadline: str | None
    education_requirement: str | None
    required_skills: list[str] = Field(default_factory=list)


class JobExtractionEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    dataset_kind: DatasetKind
    source_text: str = Field(min_length=20, max_length=30_000)
    expected: ExtractionExpected
    source_reference: str | None = Field(default=None, min_length=1, max_length=2048)
    source_captured_at: date | None = None
    annotation: EvalAnnotation | None = None

    @model_validator(mode="after")
    def require_acceptance_provenance(self) -> "JobExtractionEvalCase":
        if self.dataset_kind == "human_annotated_acceptance_v1":
            if self.source_reference is None or self.source_captured_at is None:
                raise ValueError("Human acceptance job cases require source reference and capture date")
            if self.annotation is None:
                raise ValueError("Human acceptance job cases require annotation metadata")
        return self


class RAGEvalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str = Field(min_length=1, max_length=6000)
    relevant: bool
    source_reference: str | None = Field(default=None, min_length=1, max_length=2048)
    source_captured_at: date | None = None


class RAGEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    dataset_kind: DatasetKind
    category: Literal["answer", "conflict", "stale", "no_answer"]
    question: str = Field(min_length=3, max_length=1000)
    as_of_date: date | None = None
    documents: list[RAGEvalDocument] = Field(min_length=1, max_length=20)
    expected_mode: Literal["answer", "conflict", "insufficient"]
    security_probe: bool = False
    annotation: EvalAnnotation | None = None

    @model_validator(mode="after")
    def require_acceptance_provenance(self) -> "RAGEvalCase":
        if self.dataset_kind == "human_annotated_acceptance_v1":
            if self.annotation is None:
                raise ValueError("Human acceptance RAG cases require annotation metadata")
            if self.as_of_date is None:
                raise ValueError("Human acceptance RAG cases require an as_of_date")
            if any(
                document.source_reference is None or document.source_captured_at is None
                for document in self.documents
            ):
                raise ValueError("Human acceptance RAG documents require source reference and capture date")
            if self.expected_mode == "conflict" and self.annotation.reviewer_id is None:
                raise ValueError("Conflicting human acceptance cases require a second reviewer")
        relevant_count = sum(document.relevant for document in self.documents)
        expected_by_category = {
            "answer": "answer",
            "conflict": "conflict",
            "stale": "insufficient",
            "no_answer": "insufficient",
        }
        if self.expected_mode != expected_by_category[self.category]:
            raise ValueError("RAG category and expected_mode are inconsistent")
        if self.category == "answer" and relevant_count < 1:
            raise ValueError("Answerable RAG cases require at least one relevant source")
        if self.category == "conflict" and relevant_count < 2:
            raise ValueError("Conflicting RAG cases require at least two relevant sources")
        if self.category == "stale" and relevant_count:
            raise ValueError("Stale sources cannot support a current factual answer")
        if self.category == "no_answer" and relevant_count:
            raise ValueError("No-answer RAG cases must not label a source as relevant")
        if (
            self.dataset_kind == "human_annotated_acceptance_v1"
            and self.category == "stale"
            and not any(
                document.source_captured_at is not None
                and self.as_of_date is not None
                and document.source_captured_at < self.as_of_date
                for document in self.documents
            )
        ):
            raise ValueError("Stale RAG cases require a source captured before as_of_date")
        if len({document.id for document in self.documents}) != len(self.documents):
            raise ValueError("RAG case document IDs must be unique")
        if self.security_probe and self.category != "no_answer":
            raise ValueError("Security probes must use the no_answer category")
        return self

    @property
    def relevant_source_ids(self) -> set[UUID]:
        return {document.id for document in self.documents if document.relevant}
