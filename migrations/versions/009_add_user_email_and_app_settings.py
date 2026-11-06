"""add users.email and app_settings

Revision ID: 009
Revises: 008
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint('uq_users_email', ['email'])
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=80), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('app_settings')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.drop_column('email')
