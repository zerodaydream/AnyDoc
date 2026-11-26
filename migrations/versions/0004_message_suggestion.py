"""message suggestion (uncited next-step hint shown under an answer)

Revision ID: 0004_message_suggestion
Revises: 0003_message_reasoning
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_message_suggestion"
down_revision = "0003_message_reasoning"


def upgrade() -> None:
    op.add_column("messages", sa.Column("suggestion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "suggestion")
