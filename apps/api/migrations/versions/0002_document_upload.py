"""document upload: UPLOADING state, size_bytes, anonymous users

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD_STATUSES = "'UPLOADED','QUEUED','PROCESSING','EXTRACTING','INDEXING','READY','FAILED'"


def upgrade() -> None:
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'UPLOADING' BEFORE 'UPLOADED'")
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=False))
    op.create_check_constraint("ck_documents_size_bytes", "documents", "size_bytes > 0")
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE email IS NULL")  # cascades to their documents
    op.alter_column("users", "email", existing_type=sa.String(320), nullable=False)
    op.drop_constraint("ck_documents_size_bytes", "documents")
    op.drop_column("documents", "size_bytes")
    # Postgres cannot drop an enum value; rebuild the type without UPLOADING.
    op.execute("UPDATE documents SET status = 'FAILED' WHERE status = 'UPLOADING'")
    op.execute("ALTER TYPE document_status RENAME TO document_status_old")
    op.execute(f"CREATE TYPE document_status AS ENUM ({OLD_STATUSES})")
    op.execute(
        "ALTER TABLE documents ALTER COLUMN status TYPE document_status "
        "USING status::text::document_status"
    )
    op.execute("DROP TYPE document_status_old")
