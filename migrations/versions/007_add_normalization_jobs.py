"""add normalization_jobs and normalization_job_chunks

Backs the background normalization worker: a Document's "Normalize" import
path now creates a queued NormalizationJob (with one NormalizationJobChunk
per chunk) instead of calling the model inline, so worker.py can pick it up
and persist annotations incrementally as each chunk comes back.

Revision ID: 007
Revises: 006
Create Date: 2026-06-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'normalization_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('separator', sa.String(length=10), nullable=False, server_default='\n'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name='check_normalization_job_status_valid'
        ),
    )
    op.create_table(
        'normalization_job_chunks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('normalization_jobs.id'), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('part_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('orig', sa.Text(), nullable=False),
        sa.Column('reg', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('normalization_job_chunks')
    op.drop_table('normalization_jobs')
