"""message web lookup result (kept apart from document segments)

Revision ID: 0005_message_web
Revises: 0004_message_suggestion
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_message_web"
down_revision = "0004_message_suggestion"


def upgrade() -> None:
    op.add_column("messages", sa.Column("web", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "web")
