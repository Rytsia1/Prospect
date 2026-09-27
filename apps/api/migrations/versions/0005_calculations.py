"""calculations

Revision ID: 0005
Revises: 0004
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

METRICS = [  # inputs of the current ratio
    (
        "current_assets",
        "Total current assets",
        "balance_sheet",
        "Total current assets at the reporting date.",
    ),
    (
        "current_liabilities",
        "Total current liabilities",
        "balance_sheet",
        "Total current liabilities at the reporting date.",
    ),
]


def _metric_id(key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"prospect:metric:{key}")


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_financial_facts_identity", "financial_facts", ["id", "document_id"]
    )
    op.create_table(
        "calculations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("formula_key", sa.String(length=64), nullable=False),
        sa.Column(
            "period_type",
            postgresql.ENUM(
                "annual", "quarter", "interim", "instant", name="period_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum("calculated", "not_possible", name="calculation_status"),
            nullable=False,
        ),
        sa.Column("result_numeric", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "notes",
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
            "(status = 'calculated') = (result_numeric IS NOT NULL)",
            name="ck_calculations_result",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_calculations_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "document_id", name="uq_calculations_identity"),
        sa.UniqueConstraint(
            "document_id",
            "metric_key",
            "period_type",
            "period_label",
            name="uq_calculations_period",
        ),
    )
    op.create_table(
        "calculation_inputs",
        sa.Column("calculation_id", sa.Uuid(), nullable=False),
        sa.Column("financial_fact_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["calculation_id", "document_id"],
            ["calculations.id", "calculations.document_id"],
            name="fk_calculation_inputs_calculation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["financial_fact_id", "document_id"],
            ["financial_facts.id", "financial_facts.document_id"],
            name="fk_calculation_inputs_fact",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("calculation_id", "financial_fact_id"),
    )
    op.create_index(
        "ix_calculation_inputs_fact",
        "calculation_inputs",
        ["financial_fact_id", "document_id"],
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
            {"id": _metric_id(k), "key": k, "name": n, "category": c, "description": d}
            for k, n, c, d in METRICS
        ],
    )
    # Reprocess documents that are already READY so they gain the new facts and calculations.
    op.execute(
        "INSERT INTO processing_jobs (id, document_id, status, attempts) "
        "SELECT gen_random_uuid(), id, 'queued', 0 FROM documents WHERE status = 'READY'"
    )


def downgrade() -> None:
    op.drop_index("ix_calculation_inputs_fact", table_name="calculation_inputs")
    op.drop_table("calculation_inputs")
    op.drop_table("calculations")
    op.execute("DROP TYPE IF EXISTS calculation_status")
    ids = ", ".join(f"'{_metric_id(k)}'" for k, *_ in METRICS)
    # Facts cascade from their evidence; then the metric rows can go.
    # ids are uuid5 constants computed from METRICS in this file, never external input.
    op.execute(
        "DELETE FROM evidence WHERE id IN "  # noqa: S608
        f"(SELECT evidence_id FROM financial_facts WHERE metric_id IN ({ids}))"
    )
    op.execute(f"DELETE FROM financial_metrics WHERE id IN ({ids})")  # noqa: S608
    op.drop_constraint("uq_financial_facts_identity", "financial_facts", type_="unique")
