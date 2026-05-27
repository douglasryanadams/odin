"""create signups table

Revision ID: 0001_create_signups
Revises:
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_create_signups"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signups",
        sa.Column("email_hash", sa.Text(), primary_key=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("login_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_signups_first_seen", "signups", ["first_seen"])


def downgrade() -> None:
    op.drop_index("ix_signups_first_seen", table_name="signups")
    op.drop_table("signups")
