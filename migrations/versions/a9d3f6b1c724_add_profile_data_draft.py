"""add profiles.profile_data_draft (re-edits stay unpublished until saved)

Revision ID: a9d3f6b1c724
Revises: f2a8d6c4b913
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a9d3f6b1c724'
down_revision = 'f2a8d6c4b913'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('profiles', sa.Column('profile_data_draft',
                                        postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade():
    op.drop_column('profiles', 'profile_data_draft')
