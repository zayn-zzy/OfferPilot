"""Add owner-scoped companies, job postings, applications, and stage history.

Revision ID: 20261031_0003
Revises: 20261030_0002
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa

revision = "20261031_0003"
down_revision = "20261030_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create private job-management and application-board tables."""

    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("recruitment_url", sa.String(length=2048), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_companies_owner_name"),
    )
    op.create_index("ix_companies_user_id", "companies", ["user_id"], unique=False)

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("job_type", sa.String(length=80), nullable=True),
        sa.Column("batch", sa.String(length=120), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("education_requirement", sa.String(length=120), nullable=True),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("normalized_source_url", sa.String(length=2048), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_source_url", name="uq_jobs_owner_source_url"),
    )
    op.create_index("ix_job_postings_user_id", "job_postings", ["user_id"], unique=False)
    op.create_index("ix_job_postings_company_id", "job_postings", ["company_id"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("applied_at", sa.Date(), nullable=True),
        sa.Column("resume_version_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_action", sa.String(length=500), nullable=True),
        sa.Column("next_action_due", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_version_id"], ["resume_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "job_id", name="uq_applications_owner_job"),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"], unique=False)
    op.create_index("ix_applications_job_id", "applications", ["job_id"], unique=False)

    op.create_table(
        "application_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_status_events_user_id",
        "application_status_events",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_application_status_events_application_id",
        "application_status_events",
        ["application_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove job-management tables in dependency order."""

    op.drop_index(
        "ix_application_status_events_application_id",
        table_name="application_status_events",
    )
    op.drop_index("ix_application_status_events_user_id", table_name="application_status_events")
    op.drop_table("application_status_events")
    op.drop_index("ix_applications_job_id", table_name="applications")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_job_postings_company_id", table_name="job_postings")
    op.drop_index("ix_job_postings_user_id", table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_index("ix_companies_user_id", table_name="companies")
    op.drop_table("companies")
