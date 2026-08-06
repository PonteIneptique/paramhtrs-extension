import os

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from .models import db, Line, Document, Annotation
from .annot_utils import apply_deletion_to_annotations
from .bp_auth import requires_access

bp_norm = Blueprint(
    "bp_norm", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path=''
)


# -------------------------
# Ingestion wizard entry point
# -------------------------

@bp_norm.route("/ingestion/new")
@login_required
def ingestion_new():
    from .models import Folder
    project_id = request.args.get("project_id", type=int)
    folder_id = request.args.get("folder_id", type=int)
    folder = None
    if folder_id:
        folder = Folder.query.get_or_404(folder_id)
        if not folder.user_has_access(current_user):
            abort(403)
    return render_template("ingestion/create.html",
                           project_id=project_id,
                           folder_id=folder_id,
                           folder=folder)


# -------------------------
# Single-annotation upsert (hot path: validate, edit, create)
# -------------------------

@bp_norm.route("/api/documents/<int:document_id>/annotations/<annotation_id>", methods=["PUT"])
@requires_access(Document, 'document_id')
def api_page_save_annotation(document: Document, annotation_id: str):
    data = request.json
    if not data or data.get("id") != annotation_id:
        abort(400)
    Annotation.upsert_from_dict(document.id, data)
    db.session.commit()
    return jsonify({"status": "ok"})


@bp_norm.route("/api/documents/<int:document_id>/annotations/<annotation_id>", methods=["DELETE"])
@requires_access(Document, 'document_id')
def api_page_delete_annotation(document: Document, annotation_id: str):
    Annotation.query.filter_by(id=annotation_id, document_id=document.id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Bulk replace — kept for structural operations (line deletion, clear pending)
# -------------------------

@bp_norm.route("/api/documents/<int:document_id>/annotations", methods=["PUT"])
@requires_access(Document, 'document_id')
def api_page_save_annotations(document: Document):
    data = request.json
    document.set_annotations(data.get("annotations", []))
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Delete a line
# -------------------------

@bp_norm.route("/api/lines/<int:line_id>/delete", methods=["POST", "DELETE"])
@requires_access(Line, 'line_id')
def line_delete(line: Line):
    """Delete a line and re-offset the document's annotations in one transaction.

    Annotation offsets are absolute positions into Document.full_text, which is
    derived live from the lines table — so removing a line shifts every offset
    after it. Doing both here keeps the two in sync even if the browser goes away.
    """
    document = line.part.document
    lines = document.lines
    idx = lines.index(line)
    old_text = document.full_text

    starts = [o["start"] for o in document.line_offsets]
    start, end = starts[idx], starts[idx] + len(line.original_text)
    if idx < len(lines) - 1:
        d0, d1 = start, end + 1        # the line and its trailing newline
    elif idx > 0:
        d0, d1 = start - 1, end        # last of several: the preceding newline
    else:
        d0, d1 = start, end            # only line in the document

    # Derive the post-deletion text by cutting the same range, rather than
    # re-reading document.full_text through a collection that may still hold
    # the deleted instance.
    full_text = old_text[:d0] + old_text[d1:]

    db.session.delete(line)
    rows = Annotation.query.filter_by(document_id=document.id).all()
    for dropped in apply_deletion_to_annotations(rows, d0, d1, full_text):
        db.session.delete(dropped)
    db.session.commit()

    return jsonify({
        "status": "ok",
        "document_id": document.id,
        "full_text": full_text,
        "part_offsets": document.part_offsets,
    })
