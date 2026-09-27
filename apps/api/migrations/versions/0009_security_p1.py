"""P1 security: threat-scan result, indexes for ownership, cleanup and deletion cascades

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("threat_scan", sa.String(length=20), nullable=True))
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_documents_user_id_company_id", "documents", ["user_id", "company_id"])
    op.create_index("ix_calculation_inputs_document_id", "calculation_inputs", ["document_id"])
    op.create_index("ix_extraction_reviews_fact_id", "extraction_reviews", ["fact_id"])
    op.create_index("ix_scenarios_document_id", "scenarios", ["document_id"])
    op.create_index(
        "ix_document_comparisons_document_a_id", "document_comparisons", ["document_a_id"]
    )
    op.create_index(
        "ix_document_comparisons_document_b_id", "document_comparisons", ["document_b_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_comparisons_document_b_id", table_name="document_comparisons")
    op.drop_index("ix_document_comparisons_document_a_id", table_name="document_comparisons")
    op.drop_index("ix_scenarios_document_id", table_name="scenarios")
    op.drop_index("ix_extraction_reviews_fact_id", table_name="extraction_reviews")
    op.drop_index("ix_calculation_inputs_document_id", table_name="calculation_inputs")
    op.drop_index("ix_documents_user_id_company_id", table_name="documents")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_column("documents", "threat_scan")
