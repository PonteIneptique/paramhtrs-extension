"""add annotation gap_before/gap_after and 'for_review' page status

Revision ID: 004
Revises: 003
Create Date: 2026-06-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_gap_before', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('body_gap_after', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.drop_constraint('check_page_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_page_status_valid',
            "status IN ('pending', 'active', 'done', 'for_review')"
        )


def downgrade():
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.drop_constraint('check_page_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_page_status_valid',
            "status IN ('pending', 'active', 'done')"
        )
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_column('body_gap_after')
        batch_op.drop_column('body_gap_before')
