"""Persist exact, expiring approvals for allowlisted external actions.

Revision ID: 20261104_0009
Revises: 20261102_0008
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa

revision = "20261104_0009"
down_revision = "20261102_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the external action approval and execution ledger."""

    op.create_table(
        "external_action_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("target", sa.String(length=320), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("approval_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_external_action_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_external_action_approvals_user_id", "external_action_approvals", ["user_id"]
    )
    op.create_index(
        "ix_external_action_owner_status",
        "external_action_approvals",
        ["user_id", "status"],
    )


def downgrade() -> None:
    """Remove the external action approval ledger."""

    op.drop_index("ix_external_action_owner_status", table_name="external_action_approvals")
    op.drop_index("ix_external_action_approvals_user_id", table_name="external_action_approvals")
    op.drop_table("external_action_approvals")
