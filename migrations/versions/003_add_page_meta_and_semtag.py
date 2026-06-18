"""add page qid/original_filename and annotation body_semtag

Revision ID: 003
Revises: 002
Create Date: 2026-06-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('qid', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('original_filename', sa.String(length=500), nullable=True))
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_semtag', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_column('body_semtag')
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.drop_column('original_filename')
        batch_op.drop_column('qid')
