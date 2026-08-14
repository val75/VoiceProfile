"""add profiles.sms_consent_at

Revision ID: c3f81a92d5e0
Revises: b7e2a91c4f08
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f81a92d5e0'
down_revision = 'b7e2a91c4f08'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'profiles',
        sa.Column('sms_consent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('profiles', 'sms_consent_at')
