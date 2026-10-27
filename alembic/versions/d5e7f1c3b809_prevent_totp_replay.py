"""Track the last accepted TOTP counter to prevent replay."""

from alembic import op
import sqlalchemy as sa

revision = "d5e7f1c3b809"
down_revision = "c4d8e1a92f70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_last_totp_counter", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_last_totp_counter")