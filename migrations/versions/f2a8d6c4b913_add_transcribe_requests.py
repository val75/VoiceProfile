"""add transcribe_requests table (rate limiting /voice/transcribe)

Revision ID: f2a8d6c4b913
Revises: e7b3c5d18a42
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a8d6c4b913'
down_revision = 'e7b3c5d18a42'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'transcribe_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_transcribe_requests_ip', 'transcribe_requests', ['ip'])
    op.create_index('ix_transcribe_requests_created_at', 'transcribe_requests', ['created_at'])


def downgrade():
    op.drop_index('ix_transcribe_requests_created_at', table_name='transcribe_requests')
    op.drop_index('ix_transcribe_requests_ip', table_name='transcribe_requests')
    op.drop_table('transcribe_requests')
