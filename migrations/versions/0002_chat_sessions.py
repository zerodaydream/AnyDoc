"""chat sessions: per-conversation context

Revision ID: 0002_chat_sessions
Revises: 04e83a227a91
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_chat_sessions"
down_revision = "04e83a227a91"


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
    )
    op.create_index("ix_chat_sessions_document_id", "chat_sessions", ["document_id"])
    op.create_index("ix_chat_sessions_owner_id", "chat_sessions", ["owner_id"])
    op.create_index("ix_chat_sessions_workspace_id", "chat_sessions", ["workspace_id"])
    op.create_index("ix_chat_sessions_owner_updated", "chat_sessions", ["owner_id", "updated_at"])

    op.add_column("messages", sa.Column("session_id", sa.UUID(), nullable=True))
    # Existing history (one thread per document) becomes one session per document.
    op.execute("""
        INSERT INTO chat_sessions (id, document_id, title, created_at, updated_at, owner_id, workspace_id)
        SELECT gen_random_uuid(), m.document_id,
               left((array_agg(m.content ORDER BY m.created_at) FILTER (WHERE m.role = 'user'))[1], 200),
               min(m.created_at), max(m.created_at), min(m.owner_id::text)::uuid, min(m.workspace_id::text)::uuid
        FROM messages m GROUP BY m.document_id
    """)
    op.execute("UPDATE messages m SET session_id = s.id FROM chat_sessions s WHERE s.document_id = m.document_id")
    op.alter_column("messages", "session_id", nullable=False)
    op.create_foreign_key("fk_messages_session", "messages", "chat_sessions", ["session_id"], ["id"], ondelete="CASCADE")
    op.drop_index("ix_messages_document_created", table_name="messages")
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])
    op.drop_constraint("messages_document_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "document_id")


def downgrade() -> None:
    op.add_column("messages", sa.Column("document_id", postgresql.UUID(), nullable=True))
    op.execute("UPDATE messages m SET document_id = s.document_id FROM chat_sessions s WHERE s.id = m.session_id")
    op.alter_column("messages", "document_id", nullable=False)
    op.create_foreign_key("messages_document_id_fkey", "messages", "documents", ["document_id"], ["id"], ondelete="CASCADE")
    op.drop_index("ix_messages_session_created", table_name="messages")
    op.create_index("ix_messages_document_created", "messages", ["document_id", "created_at"])
    op.drop_constraint("fk_messages_session", "messages", type_="foreignkey")
    op.drop_column("messages", "session_id")
    op.drop_table("chat_sessions")
