"""Store encrypted model provider credentials per user.

Revision ID: 20261104_0010
Revises: 20261104_0009
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa

revision = "20261104_0010"
down_revision = "20261104_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create user-scoped provider settings; secret values are ciphertext only."""

    op.create_table(
        "user_model_configurations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("llm_api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Delete stored provider settings."""

    op.drop_table("user_model_configurations")
