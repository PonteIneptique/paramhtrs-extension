"""add body_reason to annotations

Revision ID: 002
Revises: 001
Create Date: 2026-05-02 08:47:33.340155

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_reason', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_column('body_reason')
