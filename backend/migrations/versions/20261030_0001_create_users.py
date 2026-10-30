"""Create user accounts.

Revision ID: 20261030_0001
Revises:
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20261030_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the account table."""

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    """Remove the account table."""

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
