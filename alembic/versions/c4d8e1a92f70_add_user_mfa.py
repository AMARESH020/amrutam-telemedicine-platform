"""Add MFA fields to users."""

from alembic import op
import sqlalchemy as sa

revision = "c4d8e1a92f70"
down_revision = "b3c9f2d6a781"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("mfa_secret_encrypted", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("mfa_recovery_codes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_recovery_codes")
    op.drop_column("users", "mfa_secret_encrypted")
    op.drop_column("users", "mfa_enabled")