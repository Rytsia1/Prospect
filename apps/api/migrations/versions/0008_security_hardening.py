"""security hardening: sessions, rate limits, upload checksum, retry backoff

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_rate_limits_expires_at", "rate_limits", ["expires_at"])
    op.add_column("documents", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "documents", sa.Column("object_deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("run_after", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "run_after")
    op.drop_column("documents", "object_deleted_at")
    op.drop_column("documents", "sha256")
    op.drop_index("ix_rate_limits_expires_at", table_name="rate_limits")
    op.drop_table("rate_limits")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
