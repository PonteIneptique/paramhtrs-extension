"""rename Page to Part, add Subpart between Part and Line

Existing single-source pages are migrated transparently: each Page becomes a
Part (same id, label, order, status, qid), and one Subpart is created under it
(order=0, original_filename copied from the old Page.original_filename) to
hold its Lines. Annotation moves from page-scoped to part-scoped (same value,
since Part keeps the old Page's id) so a Part's full_text/annotations can span
multiple Subparts going forward.

Revision ID: 005
Revises: 004
Create Date: 2026-06-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table('pages', 'parts')
    op.rename_table('page_work', 'part_work')

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_constraint('check_page_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_part_status_valid',
            "status IN ('pending', 'active', 'done', 'for_review')"
        )

    with op.batch_alter_table('part_work', schema=None) as batch_op:
        batch_op.alter_column('page_id', new_column_name='part_id')

    op.create_table('subparts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['part_id'], ['parts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # One subpart per existing part, carrying over its original_filename.
    op.execute(
        'INSERT INTO subparts (part_id, "order", original_filename) '
        'SELECT id, 0, original_filename FROM parts'
    )

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_column('original_filename')

    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subpart_id', sa.Integer(), nullable=True))
    op.execute(
        'UPDATE lines SET subpart_id = ('
        '  SELECT s.id FROM subparts s WHERE s.part_id = lines.page_id'
        ')'
    )
    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.alter_column('subpart_id', nullable=False)
        batch_op.drop_column('page_id')
        batch_op.create_foreign_key('fk_lines_subpart_id', 'subparts', ['subpart_id'], ['id'])

    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.alter_column('page_id', new_column_name='part_id')
    op.drop_index('ix_annotations_page_id', table_name='annotations')
    op.create_index('ix_annotations_part_id', 'annotations', ['part_id'], unique=False)


def downgrade():
    op.drop_index('ix_annotations_part_id', table_name='annotations')
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.alter_column('part_id', new_column_name='page_id')
    op.create_index('ix_annotations_page_id', 'annotations', ['page_id'], unique=False)

    with op.batch_alter_table('part_work', schema=None) as batch_op:
        batch_op.alter_column('part_id', new_column_name='page_id')

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_constraint('check_part_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_page_status_valid',
            "status IN ('pending', 'active', 'done', 'for_review')"
        )
        batch_op.add_column(sa.Column('original_filename', sa.String(length=500), nullable=True))

    op.rename_table('part_work', 'page_work')
    op.rename_table('parts', 'pages')

    op.execute(
        'UPDATE pages SET original_filename = ('
        '  SELECT s.original_filename FROM subparts s WHERE s.part_id = pages.id AND s."order" = 0'
        ')'
    )

    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('page_id', sa.Integer(), nullable=True))
    op.execute(
        'UPDATE lines SET page_id = ('
        '  SELECT s.part_id FROM subparts s WHERE s.id = lines.subpart_id'
        ')'
    )
    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.alter_column('page_id', nullable=False)
        batch_op.drop_constraint('fk_lines_subpart_id', type_='foreignkey')
        batch_op.drop_column('subpart_id')
        batch_op.create_foreign_key('fk_lines_page_id', 'pages', ['page_id'], ['id'])

    op.drop_table('subparts')
