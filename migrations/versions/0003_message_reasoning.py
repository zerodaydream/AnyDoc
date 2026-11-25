"""message reasoning (model thought summaries)

Revision ID: 0003_message_reasoning
Revises: 0002_chat_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_message_reasoning"
down_revision = "0002_chat_sessions"


def upgrade() -> None:
    op.add_column("messages", sa.Column("reasoning", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "reasoning")
