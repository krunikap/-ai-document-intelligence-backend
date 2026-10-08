"""add document processing progress and chunk embeddings

Revision ID: 8a7f2c1d9b43
Revises: 3bdab0155ba0
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "8a7f2c1d9b43"
down_revision: Union[str, Sequence[str], None] = "3bdab0155ba0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "documents",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "documents",
        sa.Column("stage", sa.String(length=40), nullable=False, server_default="QUEUED"),
    )
    op.alter_column("documents", "progress", server_default=None)
    op.alter_column("documents", "stage", server_default=None)

    op.add_column(
        "document_chunks",
        sa.Column("embedding", Vector(384), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "embedding")
    op.drop_column("documents", "stage")
    op.drop_column("documents", "progress")
