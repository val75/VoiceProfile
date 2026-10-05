"""add admin_users and admin_identities tables

Revision ID: d213e5e9336f
Revises: d4a7f2c9b810
Create Date: 2026-10-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd213e5e9336f'
down_revision = 'd4a7f2c9b810'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # Mirrors the model's `unique=True, index=True` on email, which SQLAlchemy
    # renders as a single UNIQUE INDEX (not a separate unique constraint).
    op.create_index('ix_admin_users_email', 'admin_users', ['email'], unique=True)

    op.create_table(
        'admin_identities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_user_id', sa.Integer(), nullable=False),
        sa.Column('issuer', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('issuer', 'subject', name='uq_admin_identity_issuer_subject'),
        sa.UniqueConstraint('admin_user_id', 'issuer', name='uq_admin_identity_user_issuer'),
    )
    op.create_index('ix_admin_identities_admin_user_id', 'admin_identities', ['admin_user_id'])


def downgrade():
    op.drop_index('ix_admin_identities_admin_user_id', table_name='admin_identities')
    op.drop_table('admin_identities')
    op.drop_index('ix_admin_users_email', table_name='admin_users')
    op.drop_table('admin_users')
