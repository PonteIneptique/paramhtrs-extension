"""add body_cert to annotations

Revision ID: 008
Revises: 007
Create Date: 2026-08-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_cert', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_column('body_cert')
