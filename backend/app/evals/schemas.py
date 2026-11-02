"""Strict data contracts for synthetic Agent evaluation cases."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    dataset_kind: Literal["synthetic_smoke_v1"]
    source_text: str = Field(min_length=20, max_length=30_000)
    expected: ExtractionExpected


class RAGEvalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str = Field(min_length=1, max_length=6000)
    relevant: bool


class RAGEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    dataset_kind: Literal["synthetic_smoke_v1"]
    category: Literal["answer", "conflict", "stale", "no_answer"]
    question: str = Field(min_length=3, max_length=1000)
    documents: list[RAGEvalDocument] = Field(min_length=1, max_length=20)
    expected_mode: Literal["answer", "conflict", "insufficient"]
    security_probe: bool = False

    @property
    def relevant_source_ids(self) -> set[UUID]:
        return {document.id for document in self.documents if document.relevant}
