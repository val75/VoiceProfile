"""add otp_codes table

Revision ID: b7e2a91c4f08
Revises: cae1bde8aad1
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e2a91c4f08'
down_revision = 'cae1bde8aad1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'otp_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_otp_codes_phone', 'otp_codes', ['phone'])


def downgrade():
    op.drop_index('ix_otp_codes_phone', table_name='otp_codes')
    op.drop_table('otp_codes')
