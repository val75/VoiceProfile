"""initial schema: profiles + reviews

Revision ID: e5c9a1f3b207
Revises:
Create Date: 2026-08-07

Squashed baseline that creates the base tables from an empty database. Replaces
the earlier divergent migration histories (the laptop's incremental chain vs the
server's own initial migration) that drifted apart while migrations/ was
gitignored. Matches models/profile.py and models/review.py on main (no locale;
that column belongs to the i18n branch and returns when it merges).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e5c9a1f3b207'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=True),
        sa.Column('phone_number', sa.String(length=20), nullable=True),
        sa.Column('onboarding_state', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('profile_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('transcripts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('photo', sa.LargeBinary(), nullable=True),
        sa.Column('photo_mime', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_profiles_phone_number', 'profiles', ['phone_number'], unique=True)

    op.create_table(
        'reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('reviewer_name', sa.String(length=120), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reviews_profile_id', 'reviews', ['profile_id'], unique=False)


def downgrade():
    op.drop_index('ix_reviews_profile_id', table_name='reviews')
    op.drop_table('reviews')
    op.drop_index('ix_profiles_phone_number', table_name='profiles')
    op.drop_table('profiles')
