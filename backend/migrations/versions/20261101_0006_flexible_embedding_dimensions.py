"""Allow the configured embedding model's native vector dimension.

Revision ID: 20261101_0006
Revises: 20261101_0005
Create Date: 2026-11-01
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

revision = "20261101_0006"
down_revision = "20261101_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store each vector's actual dimensions and use pgvector's exact search."""

    bind = op.get_bind()
    op.add_column(
        "document_chunks",
        sa.Column("embedding_dimensions", sa.Integer(), server_default="1536", nullable=False),
    )
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
        op.alter_column(
            "document_chunks",
            "embedding",
            existing_type=VECTOR(1536),
            type_=VECTOR(),
            postgresql_using="embedding::vector",
        )


def downgrade() -> None:
    """Restore the original fixed-width schema when all vectors are 1536D."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        non_1536_count = bind.execute(
            sa.text("SELECT count(*) FROM document_chunks WHERE embedding_dimensions != 1536")
        ).scalar_one()
        if non_1536_count:
            raise RuntimeError("Cannot restore vector(1536) while other vector dimensions exist")
        op.alter_column(
            "document_chunks",
            "embedding",
            existing_type=VECTOR(),
            type_=VECTOR(1536),
            postgresql_using="embedding::vector(1536)",
        )
        op.create_index(
            "ix_document_chunks_embedding_hnsw",
            "document_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        )
    op.drop_column("document_chunks", "embedding_dimensions")
