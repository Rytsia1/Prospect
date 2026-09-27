"""financial facts

Revision ID: 0004
Revises: 0003
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


METRICS = [  # key, name, category, description
    ("revenue", "Revenue", "income_statement", "Total revenue or net sales for the period."),
    ("gross_profit", "Gross profit", "income_statement", "Revenue less cost of revenue."),
    ("operating_income", "Operating income", "income_statement", "Profit from operations."),
    ("net_income", "Net income", "income_statement", "Profit for the period."),
    ("total_assets", "Total assets", "balance_sheet", "Total assets at the reporting date."),
    (
        "total_liabilities",
        "Total liabilities",
        "balance_sheet",
        "Total liabilities at the reporting date.",
    ),
    ("equity", "Total equity", "balance_sheet", "Total equity at the reporting date."),
    (
        "cash",
        "Cash and cash equivalents",
        "balance_sheet",
        "Cash and cash equivalents at the reporting date.",
    ),
    (
        "total_debt",
        "Total debt",
        "debt",
        "Total debt or total borrowings exactly as reported by the company. Never derived by "
        "summing components.",
    ),
]


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_document_chunks_page_identity", "document_chunks", ["id", "page_id"]
    )
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column(
            "evidence_type", sa.Enum("table_row", "text_line", name="evidence_type"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "page_id"],
            ["document_chunks.id", "document_chunks.page_id"],
            name="fk_evidence_chunk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_evidence_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "document_id", "page_number"],
            ["document_pages.id", "document_pages.document_id", "document_pages.page_number"],
            name="fk_evidence_page",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "document_id"],
            ["document_sections.id", "document_sections.document_id"],
            name="fk_evidence_section",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "document_id", name="uq_evidence_identity"),
    )
    op.create_index(
        "ix_evidence_document_id_page_id", "evidence", ["document_id", "page_id"], unique=False
    )
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("metric_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("scale", sa.String(length=16), nullable=False),
        sa.Column("original_text", sa.String(length=100), nullable=False),
        sa.Column("original_unit", sa.Text(), nullable=True),
        sa.Column(
            "period_type",
            sa.Enum("annual", "quarter", "interim", "instant", name="period_type"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("extraction_method", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.Enum("accepted", "needs_review", name="fact_status"), nullable=False
        ),
        sa.Column(
            "review_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR currency IS NOT NULL", name="ck_financial_facts_currency"
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_financial_facts_confidence"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_financial_facts_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "document_id"],
            ["evidence.id", "evidence.document_id"],
            name="fk_financial_facts_evidence",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["financial_metrics.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_facts_document_metric_period",
        "financial_facts",
        ["document_id", "metric_id", "period_end"],
        unique=False,
    )
    op.create_index(
        "uq_financial_facts_accepted",
        "financial_facts",
        ["document_id", "metric_id", "period_type", "period_label"],
        unique=True,
        postgresql_where="status = 'accepted'",
    )

    metrics = sa.table(
        "financial_metrics",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        metrics,
        [
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"prospect:metric:{key}"),
                "key": key,
                "name": name,
                "category": category,
                "description": description,
            }
            for key, name, category, description in METRICS
        ],
    )
    # Documents processed before extraction existed get queued again so they gain facts.
    op.execute(
        "INSERT INTO processing_jobs (id, document_id, status, attempts) "
        "SELECT gen_random_uuid(), id, 'queued', 0 FROM documents WHERE status = 'READY'"
    )


def downgrade() -> None:
    op.drop_index(
        "uq_financial_facts_accepted",
        table_name="financial_facts",
        postgresql_where="status = 'accepted'",
    )
    op.drop_index("ix_financial_facts_document_metric_period", table_name="financial_facts")
    op.drop_table("financial_facts")
    op.drop_index("ix_evidence_document_id_page_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_table("financial_metrics")
    op.drop_constraint("uq_document_chunks_page_identity", "document_chunks", type_="unique")
    for enum_type in ("fact_status", "period_type", "evidence_type"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
