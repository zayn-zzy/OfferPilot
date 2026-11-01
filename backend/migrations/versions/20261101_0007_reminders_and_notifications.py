"""Create user reminders and idempotent in-app notifications.

Revision ID: 20261101_0007
Revises: 20261101_0006
Create Date: 2026-11-01
"""

from alembic import op
import sqlalchemy as sa

revision = "20261101_0007"
down_revision = "20261101_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add reminders and their notification delivery records."""

    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Asia/Shanghai",
            nullable=False,
        ),
    )
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notify_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("lead_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("channel", sa.String(length=16), server_default="in_app", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="scheduled", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("schedule_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_error", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_reminders_owner_idempotency"
        ),
    )
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_due", "reminders", ["status", "notify_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reminder_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_notifications_owner_idempotency"
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_owner_created", "notifications", ["user_id", "created_at"]
    )


def downgrade() -> None:
    """Remove notification and reminder records."""

    op.drop_index("ix_notifications_owner_created", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_reminders_due", table_name="reminders")
    op.drop_index("ix_reminders_user_id", table_name="reminders")
    op.drop_table("reminders")
    op.drop_column("users", "timezone")
