"""rename Document->Folder, Part->Document, Subpart->Part; extract Metadata

Cascades the earlier Page->Part/Subpart rename one level further:
  documents (Document) -> folders (Folder)
  parts     (Part)     -> documents (Document)
  subparts  (Subpart)  -> parts (Part)

Also extracts per-level scalar metadata (language/qid/iiif_manifest_url on the
old Document, qid on the old Part, original_filename on the old Subpart) plus
their Work associations into a single, separable `metadata` table that any of
Folder/Document/Part link to via a nullable metadata_id FK.

Revision ID: 006
Revises: 005
Create Date: 2026-06-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ---- table/column renames (old Document -> Folder) --------------------
    op.rename_table('documents', 'folders')
    op.rename_table('document_user', 'folder_user')
    with op.batch_alter_table('folder_user', schema=None) as batch_op:
        batch_op.alter_column('document_id', new_column_name='folder_id')

    # ---- table/column renames (old Part -> Document) -----------------------
    op.rename_table('parts', 'documents')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.alter_column('document_id', new_column_name='folder_id')
        batch_op.drop_constraint('check_part_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_document_status_valid',
            "status IN ('pending', 'active', 'done', 'for_review')"
        )

    # ---- table/column renames (old Subpart -> Part) ------------------------
    op.rename_table('subparts', 'parts')
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.alter_column('part_id', new_column_name='document_id')

    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.alter_column('subpart_id', new_column_name='part_id')

    op.drop_index('ix_annotations_part_id', table_name='annotations')
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.alter_column('part_id', new_column_name='document_id')
    op.create_index('ix_annotations_document_id', 'annotations', ['document_id'], unique=False)

    # ---- new Metadata table -------------------------------------------------
    op.create_table('metadata',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('qid', sa.String(length=100), nullable=True),
        sa.Column('original_filename', sa.String(length=500), nullable=True),
        sa.Column('iiif_manifest_url', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metadata_work',
        sa.Column('metadata_id', sa.Integer(), nullable=False),
        sa.Column('work_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['metadata_id'], ['metadata.id'], ),
        sa.ForeignKeyConstraint(['work_id'], ['works.id'], ),
        sa.PrimaryKeyConstraint('metadata_id', 'work_id')
    )

    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_folders_metadata_id', 'metadata', ['metadata_id'], ['id'])
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_documents_metadata_id', 'metadata', ['metadata_id'], ['id'])
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_parts_metadata_id', 'metadata', ['metadata_id'], ['id'])

    # ---- migrate scalar fields + Work associations into Metadata rows ------
    def get_or_create_metadata_id(table, row_id, existing_metadata_id):
        if existing_metadata_id is not None:
            return existing_metadata_id
        result = bind.execute(sa.text("INSERT INTO metadata DEFAULT VALUES"))
        new_id = result.lastrowid if hasattr(result, 'lastrowid') else result.inserted_primary_key[0]
        bind.execute(sa.text(f"UPDATE {table} SET metadata_id = :mid WHERE id = :rid"),
                     {"mid": new_id, "rid": row_id})
        return new_id

    # Folders: language/qid/iiif_manifest_url
    folder_rows = bind.execute(sa.text(
        "SELECT id, metadata_id, language, qid, iiif_manifest_url FROM folders"
    )).fetchall()
    for fid, mid, language, qid, iiif in folder_rows:
        if language or qid or iiif:
            mid = get_or_create_metadata_id('folders', fid, mid)
            bind.execute(sa.text(
                "UPDATE metadata SET language = :language, qid = :qid, iiif_manifest_url = :iiif WHERE id = :mid"
            ), {"language": language, "qid": qid, "iiif": iiif, "mid": mid})

    # Folder-level works (old document_work, column document_id -> folders.id)
    folder_work_rows = bind.execute(sa.text("SELECT document_id, work_id FROM document_work")).fetchall()
    folder_metadata_by_id = {fid: mid for fid, mid, *_ in
                              bind.execute(sa.text("SELECT id, metadata_id FROM folders")).fetchall()}
    for fid, work_id in folder_work_rows:
        mid = get_or_create_metadata_id('folders', fid, folder_metadata_by_id.get(fid))
        folder_metadata_by_id[fid] = mid
        bind.execute(sa.text(
            "INSERT OR IGNORE INTO metadata_work (metadata_id, work_id) VALUES (:mid, :wid)"
        ), {"mid": mid, "wid": work_id})

    # Documents (old Part): qid
    document_rows = bind.execute(sa.text("SELECT id, metadata_id, qid FROM documents")).fetchall()
    document_metadata_by_id = {did: mid for did, mid, _ in document_rows}
    for did, mid, qid in document_rows:
        if qid:
            mid = get_or_create_metadata_id('documents', did, mid)
            document_metadata_by_id[did] = mid
            bind.execute(sa.text("UPDATE metadata SET qid = :qid WHERE id = :mid"), {"qid": qid, "mid": mid})

    # Document-level works (old part_work, column part_id -> documents.id)
    document_work_rows = bind.execute(sa.text("SELECT part_id, work_id FROM part_work")).fetchall()
    for did, work_id in document_work_rows:
        mid = get_or_create_metadata_id('documents', did, document_metadata_by_id.get(did))
        document_metadata_by_id[did] = mid
        bind.execute(sa.text(
            "INSERT OR IGNORE INTO metadata_work (metadata_id, work_id) VALUES (:mid, :wid)"
        ), {"mid": mid, "wid": work_id})

    # Parts (old Subpart): original_filename
    part_rows = bind.execute(sa.text("SELECT id, metadata_id, original_filename FROM parts")).fetchall()
    for pid, mid, original_filename in part_rows:
        if original_filename:
            mid = get_or_create_metadata_id('parts', pid, mid)
            bind.execute(sa.text(
                "UPDATE metadata SET original_filename = :fn WHERE id = :mid"
            ), {"fn": original_filename, "mid": mid})

    # ---- drop now-redundant columns/tables ----------------------------------
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_column('language')
        batch_op.drop_column('qid')
        batch_op.drop_column('iiif_manifest_url')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('qid')
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_column('original_filename')

    op.drop_table('document_work')
    op.drop_table('part_work')


def downgrade():
    bind = op.get_bind()

    op.create_table('document_work',
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('work_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['folders.id'], ),
        sa.ForeignKeyConstraint(['work_id'], ['works.id'], ),
        sa.PrimaryKeyConstraint('document_id', 'work_id')
    )
    op.create_table('part_work',
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('work_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['part_id'], ['documents.id'], ),
        sa.ForeignKeyConstraint(['work_id'], ['works.id'], ),
        sa.PrimaryKeyConstraint('part_id', 'work_id')
    )

    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('language', sa.String(length=10), nullable=False, server_default='fre'))
        batch_op.add_column(sa.Column('qid', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('iiif_manifest_url', sa.Text(), nullable=True))
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('qid', sa.String(length=100), nullable=True))
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_filename', sa.String(length=500), nullable=True))

    bind.execute(sa.text(
        "UPDATE folders SET language = COALESCE((SELECT m.language FROM metadata m WHERE m.id = folders.metadata_id), 'fre'),"
        " qid = (SELECT m.qid FROM metadata m WHERE m.id = folders.metadata_id),"
        " iiif_manifest_url = (SELECT m.iiif_manifest_url FROM metadata m WHERE m.id = folders.metadata_id)"
    ))
    bind.execute(sa.text(
        "UPDATE documents SET qid = (SELECT m.qid FROM metadata m WHERE m.id = documents.metadata_id)"
    ))
    bind.execute(sa.text(
        "UPDATE parts SET original_filename = (SELECT m.original_filename FROM metadata m WHERE m.id = parts.metadata_id)"
    ))
    bind.execute(sa.text(
        "INSERT INTO document_work (document_id, work_id) "
        "SELECT f.id, mw.work_id FROM folders f JOIN metadata_work mw ON mw.metadata_id = f.metadata_id"
    ))
    bind.execute(sa.text(
        "INSERT INTO part_work (part_id, work_id) "
        "SELECT d.id, mw.work_id FROM documents d JOIN metadata_work mw ON mw.metadata_id = d.metadata_id"
    ))

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_parts_metadata_id', type_='foreignkey')
        batch_op.drop_column('metadata_id')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_documents_metadata_id', type_='foreignkey')
        batch_op.drop_column('metadata_id')
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_constraint('fk_folders_metadata_id', type_='foreignkey')
        batch_op.drop_column('metadata_id')

    op.drop_table('metadata_work')
    op.drop_table('metadata')

    op.drop_index('ix_annotations_document_id', table_name='annotations')
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.alter_column('document_id', new_column_name='part_id')
    op.create_index('ix_annotations_part_id', 'annotations', ['part_id'], unique=False)

    with op.batch_alter_table('lines', schema=None) as batch_op:
        batch_op.alter_column('part_id', new_column_name='subpart_id')

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.alter_column('document_id', new_column_name='part_id')
    op.rename_table('parts', 'subparts')

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_constraint('check_document_status_valid', type_='check')
        batch_op.create_check_constraint(
            'check_part_status_valid',
            "status IN ('pending', 'active', 'done', 'for_review')"
        )
        batch_op.alter_column('folder_id', new_column_name='document_id')
    op.rename_table('documents', 'parts')

    with op.batch_alter_table('folder_user', schema=None) as batch_op:
        batch_op.alter_column('folder_id', new_column_name='document_id')
    op.rename_table('folder_user', 'document_user')
    op.rename_table('folders', 'documents')
