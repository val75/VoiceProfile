"""add voice_recordings table

Revision ID: e7b3c5d18a42
Revises: d213e5e9336f
Create Date: 2026-10-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b3c5d18a42'
down_revision = 'd213e5e9336f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'voice_recordings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('step', sa.String(length=20), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('audio', sa.LargeBinary(), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('stt_error', sa.Text(), nullable=True),
        sa.Column('accepted', sa.Boolean(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edited_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id', 'step', 'attempt', name='uq_voice_recording_take'),
    )
    op.create_index('ix_voice_recordings_created_at', 'voice_recordings', ['created_at'])


def downgrade():
    op.drop_index('ix_voice_recordings_created_at', table_name='voice_recordings')
    op.drop_table('voice_recordings')
