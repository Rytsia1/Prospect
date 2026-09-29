"""Currency semantics: company reporting currency, document currency, fact currency status

Revision ID: 0010
Revises: 0009

- companies.currency is renamed to reporting_currency (data kept: an IDR company stays IDR).
- documents.document_currency: the currency most of a document's verified facts use.
- financial_facts.currency_status: verified / inferred / missing / conflicting, backfilled from
  what extraction recorded; accepted and corrected facts are verified by definition.
No value or currency is converted or overwritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("companies", "currency", new_column_name="reporting_currency")

    op.add_column("financial_facts", sa.Column("currency_status", sa.String(12), nullable=True))
    op.execute(
        """
        UPDATE financial_facts SET currency_status = CASE
            WHEN status IN ('accepted', 'corrected') THEN 'verified'
            WHEN currency IS NULL THEN 'missing'
            WHEN review_reasons::text LIKE '%currency conflicts%' THEN 'conflicting'
            ELSE 'verified'
        END
        """
    )
    op.alter_column("financial_facts", "currency_status", nullable=False)
    op.create_check_constraint(
        "ck_financial_facts_currency_status",
        "financial_facts",
        "currency_status IN ('verified', 'inferred', 'missing', 'conflicting')",
    )
    op.create_check_constraint(
        "ck_financial_facts_currency_missing",
        "financial_facts",
        "(currency IS NULL) = (currency_status = 'missing')",
    )
    op.create_check_constraint(
        "ck_financial_facts_currency_verified",
        "financial_facts",
        "status NOT IN ('accepted', 'corrected') OR currency_status = 'verified'",
    )

    op.add_column("documents", sa.Column("document_currency", sa.String(3), nullable=True))
    # Same rule as extraction.document_currency: a strict majority of verified facts, else NULL.
    op.execute(
        """
        UPDATE documents AS d SET document_currency = t.currency
        FROM (
            SELECT document_id, currency, COUNT(*) AS n,
                   SUM(COUNT(*)) OVER (PARTITION BY document_id) AS total
            FROM financial_facts
            WHERE currency_status = 'verified'
            GROUP BY document_id, currency
        ) AS t
        WHERE t.document_id = d.id AND t.n * 2 > t.total
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "document_currency")
    op.drop_constraint("ck_financial_facts_currency_verified", "financial_facts", type_="check")
    op.drop_constraint("ck_financial_facts_currency_missing", "financial_facts", type_="check")
    op.drop_constraint("ck_financial_facts_currency_status", "financial_facts", type_="check")
    op.drop_column("financial_facts", "currency_status")
    op.alter_column("companies", "reporting_currency", new_column_name="currency")
