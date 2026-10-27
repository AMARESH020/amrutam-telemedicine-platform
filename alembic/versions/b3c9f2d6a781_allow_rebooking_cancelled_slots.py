"""Allow rebooking cancelled consultation slots."""

from alembic import op
import sqlalchemy as sa

revision = "b3c9f2d6a781"
down_revision = "a9b66e4148c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "consultations_slot_id_key",
        "consultations",
        type_="unique",
    )

    op.create_index(
        "uq_active_consultation_slot",
        "consultations",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("status != 'cancelled'"),
        sqlite_where=sa.text("status != 'cancelled'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_active_consultation_slot",
        table_name="consultations",
    )

    op.create_unique_constraint(
        "consultations_slot_id_key",
        "consultations",
        ["slot_id"],
    )