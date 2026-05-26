"""create search_history table

Revision ID: 0002_create_search_history
Revises: 0001_create_signups
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_search_history"
down_revision: str | None = "0001_create_signups"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email_hash", sa.Text(), nullable=True),
        sa.Column("cookie_id", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Indexes back the read paths: by user, and the anonymous cookie/IP OR-match.
    op.create_index("ix_search_history_user", "search_history", ["email_hash", "created_at"])
    op.create_index("ix_search_history_cookie", "search_history", ["cookie_id", "created_at"])
    op.create_index("ix_search_history_ip", "search_history", ["ip", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_search_history_ip", table_name="search_history")
    op.drop_index("ix_search_history_cookie", table_name="search_history")
    op.drop_index("ix_search_history_user", table_name="search_history")
    op.drop_table("search_history")
