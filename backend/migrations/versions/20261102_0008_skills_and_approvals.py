"""Add versioned skill runs, approval records, saved prep packs, and audit events.

Revision ID: 20261102_0008
Revises: 20261101_0007
Create Date: 2026-11-02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261102_0008"
down_revision = "20261101_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist skill versions and require exact approval before local draft writes."""

    op.add_column("agent_runs", sa.Column("skill_id", sa.String(length=80), nullable=True))
    op.add_column("agent_runs", sa.Column("skill_version", sa.String(length=32), nullable=True))
    op.add_column("agent_runs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("agent_runs", sa.Column("request_hash", sa.String(length=64), nullable=True))
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "resume_version_id",
                sa.Uuid(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_resume_version_id_resume_versions",
            "resume_versions",
            ["resume_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_agent_runs_owner_idempotency", ["user_id", "idempotency_key"]
        )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("approval_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approval_requests_user_id", "approval_requests", ["user_id"])
    op.create_index(
        "ix_approval_requests_owner_status", "approval_requests", ["user_id", "status"]
    )

    op.create_table(
        "application_prep_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.String(length=80), nullable=False),
        sa.Column("skill_version", sa.String(length=32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "agent_run_id", name="uq_prep_packs_owner_run"),
    )
    op.create_index("ix_application_prep_packs_user_id", "application_prep_packs", ["user_id"])
    op.create_index(
        "ix_prep_packs_owner_created", "application_prep_packs", ["user_id", "created_at"]
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_owner_created", "audit_events", ["user_id", "created_at"])


def downgrade() -> None:
    """Remove skill outputs and approval history."""

    op.drop_index("ix_audit_events_owner_created", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_prep_packs_owner_created", table_name="application_prep_packs")
    op.drop_index("ix_application_prep_packs_user_id", table_name="application_prep_packs")
    op.drop_table("application_prep_packs")
    op.drop_index("ix_approval_requests_owner_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_user_id", table_name="approval_requests")
    op.drop_table("approval_requests")
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("uq_agent_runs_owner_idempotency", type_="unique")
        batch_op.drop_constraint(
            "fk_agent_runs_resume_version_id_resume_versions", type_="foreignkey"
        )
        batch_op.drop_column("request_hash")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("skill_version")
        batch_op.drop_column("skill_id")
        batch_op.drop_column("resume_version_id")
