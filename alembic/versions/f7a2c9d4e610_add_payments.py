"""Add payment intent and reconciliation records."""
from alembic import op
import sqlalchemy as sa

revision = "f7a2c9d4e610"
down_revision = "d5e7f1c3b809"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consultation_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("provider", sa.String(length=40), server_default="unconfigured", nullable=False),
        sa.Column("provider_reference", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_payments_amount_positive"),
        sa.ForeignKeyConstraint(["consultation_id"], ["consultations.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )
    op.create_index("ix_payments_consultation_id", "payments", ["consultation_id"], unique=False)
    op.create_index("ix_payments_patient_id", "payments", ["patient_id"], unique=False)
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)
    op.create_index(
        "uq_active_payment_consultation",
        "payments",
        ["consultation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'succeeded')"),
        sqlite_where=sa.text("status IN ('pending', 'succeeded')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_payment_consultation", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_patient_id", table_name="payments")
    op.drop_index("ix_payments_consultation_id", table_name="payments")
    op.drop_table("payments")
