"""add otp_requests table (rate limiting)

Revision ID: d4a7f2c9b810
Revises: c3f81a92d5e0
Create Date: 2026-08-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4a7f2c9b810'
down_revision = 'c3f81a92d5e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'otp_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_otp_requests_phone', 'otp_requests', ['phone'])
    op.create_index('ix_otp_requests_ip', 'otp_requests', ['ip'])
    op.create_index('ix_otp_requests_created_at', 'otp_requests', ['created_at'])


def downgrade():
    op.drop_index('ix_otp_requests_created_at', table_name='otp_requests')
    op.drop_index('ix_otp_requests_ip', table_name='otp_requests')
    op.drop_index('ix_otp_requests_phone', table_name='otp_requests')
    op.drop_table('otp_requests')
