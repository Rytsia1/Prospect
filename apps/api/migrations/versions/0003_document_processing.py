"""document processing: page metadata/blocks, section order, traceable chunks

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No processor existed before this revision, so these tables hold no derived rows yet.
    op.execute("DELETE FROM document_chunks")
    op.execute("DELETE FROM document_sections")

    op.add_column(
        "document_pages",
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column(
        "document_pages",
        sa.Column("blocks", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.create_unique_constraint(
        "uq_document_pages_identity", "document_pages", ["id", "document_id", "page_number"]
    )

    op.add_column("document_sections", sa.Column("ordinal", sa.Integer(), nullable=False))
    op.alter_column("document_sections", "title", existing_type=sa.String(500), nullable=True)
    op.create_unique_constraint(
        "uq_document_sections_ordinal", "document_sections", ["document_id", "ordinal"]
    )
    op.create_unique_constraint(
        "uq_document_sections_identity", "document_sections", ["id", "document_id"]
    )
    op.create_check_constraint("ck_document_sections_ordinal", "document_sections", "ordinal >= 0")

    for column in ("document_id", "section_id"):
        op.add_column("document_chunks", sa.Column(column, sa.Uuid(), nullable=False))
    for column in ("page_number", "block_start", "block_end"):
        op.add_column("document_chunks", sa.Column(column, sa.Integer(), nullable=False))
    op.create_check_constraint(
        "ck_document_chunks_blocks",
        "document_chunks",
        "block_start >= 0 AND block_end >= block_start",
    )
    op.drop_constraint("document_chunks_page_id_fkey", "document_chunks", type_="foreignkey")
    op.create_foreign_key(
        "fk_document_chunks_document",
        "document_chunks",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_document_chunks_page",
        "document_chunks",
        "document_pages",
        ["page_id", "document_id", "page_number"],
        ["id", "document_id", "page_number"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_document_chunks_section",
        "document_chunks",
        "document_sections",
        ["section_id", "document_id"],
        ["id", "document_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_document_chunks_document_order",
        "document_chunks",
        ["document_id", "page_number", "chunk_index"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM document_chunks")
    op.execute("DELETE FROM document_sections")
    op.drop_index("ix_document_chunks_document_order", table_name="document_chunks")
    for name in (
        "fk_document_chunks_section",
        "fk_document_chunks_page",
        "fk_document_chunks_document",
    ):
        op.drop_constraint(name, "document_chunks", type_="foreignkey")
    op.create_foreign_key(
        "document_chunks_page_id_fkey",
        "document_chunks",
        "document_pages",
        ["page_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_document_chunks_blocks", "document_chunks", type_="check")
    for column in ("block_end", "block_start", "page_number", "section_id", "document_id"):
        op.drop_column("document_chunks", column)

    op.drop_constraint("ck_document_sections_ordinal", "document_sections", type_="check")
    op.drop_constraint("uq_document_sections_identity", "document_sections", type_="unique")
    op.drop_constraint("uq_document_sections_ordinal", "document_sections", type_="unique")
    op.alter_column("document_sections", "title", existing_type=sa.String(500), nullable=False)
    op.drop_column("document_sections", "ordinal")

    op.drop_constraint("uq_document_pages_identity", "document_pages", type_="unique")
    op.drop_column("document_pages", "blocks")
    op.drop_column("document_pages", "metadata")
