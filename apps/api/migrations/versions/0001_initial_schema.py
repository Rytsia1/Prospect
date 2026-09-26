"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector is used by document_chunks.embedding from Phase 5 (docs/DEPLOYMENT.md step 1).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum("annual_report", "financial_statement", "prospectus", name="document_type"),
            nullable=False,
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "QUEUED",
                "PROCESSING",
                "EXTRACTING",
                "INDEXING",
                "READY",
                "FAILED",
                name="document_status",
            ),
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("fiscal_year BETWEEN 1900 AND 2200", name="ck_documents_fiscal_year"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_documents_user_id_created_at", "documents", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "extraction_status",
            sa.Enum("success", "partial", "failed", name="page_extraction_status"),
            nullable=False,
        ),
        sa.CheckConstraint("page_number >= 1", name="ck_document_pages_page_number"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number"),
    )
    op.create_table(
        "document_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_page >= 1 AND end_page >= start_page", name="ck_document_sections_page_range"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_sections_document_id_start_page",
        "document_sections",
        ["document_id", "start_page"],
        unique=False,
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", name="job_status"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_processing_jobs_attempts"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_jobs_document_id", "processing_jobs", ["document_id"], unique=False
    )
    op.create_index(
        "ix_processing_jobs_status_created_at",
        "processing_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_chunk_index"),
        sa.ForeignKeyConstraint(["page_id"], ["document_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "chunk_index"),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_index("ix_processing_jobs_status_created_at", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_document_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_document_sections_document_id_start_page", table_name="document_sections")
    op.drop_table("document_sections")
    op.drop_table("document_pages")
    op.drop_index("ix_documents_user_id_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_table("users")
    for enum_type in ("job_status", "page_extraction_status", "document_status", "document_type"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
