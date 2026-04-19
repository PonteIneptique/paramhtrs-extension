import io
import json
import os
import zipfile

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, Response
from flask_login import login_required, current_user
from .models import db, Document, DocumentUser, DocumentWork, Work, Project, Page, Line, User
from .bp_auth import requires_access
from .annot_utils import build_tei_from_annotations

bp_document = Blueprint(
    "bp_document", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path=''
)

LANGUAGES = [
    ("fre", "French"),
    ("lat", "Latin"),
    ("spa", "Spanish"),
    ("ita", "Italian"),
    ("eng", "English"),
    ("ger", "German"),
]


def require_document_admin(document: Document):
    """Abort 403 unless the current user is a site admin, the project creator,
    or the document creator."""
    project = Project.query.get(document.project_id)
    if not (
        current_user.is_admin
        or project.creator_id == current_user.id
        or document.creator_id == current_user.id
    ):
        abort(403)


# -------------------------
# Create document
# -------------------------

@bp_document.route("/documents/new", methods=["GET", "POST"])
@login_required
def document_create():
    if request.method == "POST":
        # Support both form and JSON (called from ingestion wizard)
        if request.is_json:
            data = request.json
        else:
            data = request.form

        project_id = data.get("project_id", type=int) if not request.is_json else int(data.get("project_id", 0))
        project = Project.query.get_or_404(project_id)
        if not project.user_has_access(current_user):
            abort(403)

        doc = Document(
            name=data.get("name", "Untitled"),
            description=data.get("description", ""),
            project_id=project_id,
            creator_id=current_user.id,
            language=data.get("language", "fre"),
            qid=data.get("qid") or None,
        )
        db.session.add(doc)
        db.session.commit()

        if request.is_json:
            return jsonify({"status": "ok", "id": doc.id, "name": doc.name})
        flash("Document created", "success")
        return redirect(url_for("bp_document.document_browse", document_id=doc.id))

    # GET — show form
    project_id = request.args.get("project_id", type=int)
    project = None
    if project_id:
        project = Project.query.get_or_404(project_id)
        if not project.user_has_access(current_user):
            abort(403)
    return render_template("documents/new.html", project=project, languages=LANGUAGES)


# -------------------------
# Browse document (list pages)
# -------------------------

@bp_document.route("/documents/<int:document_id>")
@requires_access(Document, 'document_id')
def document_browse(document: Document):
    pages = Page.query.filter_by(document_id=document.id).order_by(Page.order).all()
    can_edit = (
        current_user.is_admin
        or Project.query.get(document.project_id).creator_id == current_user.id
        or document.creator_id == current_user.id
    )
    return render_template(
        "documents/edit.html",
        document=document,
        pages=pages,
        can_edit=can_edit,
        languages=LANGUAGES,
    )


# -------------------------
# Edit document metadata
# -------------------------

@bp_document.route("/documents/<int:document_id>/edit", methods=["POST"])
@requires_access(Document, 'document_id')
def document_update(document: Document):
    require_document_admin(document)
    document.name = request.form.get("name", document.name)
    document.description = request.form.get("description", document.description)
    document.language = request.form.get("language", document.language)
    document.qid = request.form.get("qid") or None
    document.iiif_manifest_url = request.form.get("iiif_manifest_url") or None
    db.session.commit()
    flash("Document updated", "success")
    return redirect(url_for("bp_document.document_browse", document_id=document.id))


# -------------------------
# Delete document
# -------------------------

@bp_document.route("/documents/<int:document_id>/delete")
@requires_access(Document, 'document_id')
def document_delete(document: Document):
    require_document_admin(document)
    if request.args.get("confirm", type=bool, default=False):
        project_id = document.project_id
        db.session.delete(document)
        db.session.commit()
        flash("Document deleted", "success")
        return redirect(url_for("bp_project.project_browse", project_id=project_id))
    return render_template("documents/delete.html", document=document)


# -------------------------
# Manage document users
# -------------------------

@bp_document.route("/documents/<int:document_id>/users")
@login_required
def document_users(document_id):
    document = Document.query.get_or_404(document_id)
    require_document_admin(document)
    users = User.query.order_by(User.username).all()
    document_user_ids = {u.id for u in document.users}
    return render_template(
        "documents/users.html",
        document=document,
        users=users,
        document_user_ids=document_user_ids,
    )


@bp_document.route("/api/documents/<int:document_id>/users")
@login_required
def api_document_users(document_id):
    document = Document.query.get_or_404(document_id)
    require_document_admin(document)
    return jsonify({
        "document_id": document.id,
        "users": [
            {"id": u.id, "username": u.username, "has_access": document.user_has_access(u)}
            for u in User.query.all()
        ],
    })


@bp_document.route("/api/documents/<int:document_id>/users/<int:user_id>", methods=["POST"])
@login_required
def api_doc_add_user(document_id, user_id):
    document = Document.query.get_or_404(document_id)
    require_document_admin(document)
    if document.creator_id == user_id:
        abort(400)
    exists = DocumentUser.query.filter_by(document_id=document_id, user_id=user_id).first()
    if not exists:
        db.session.add(DocumentUser(document_id=document_id, user_id=user_id))
        db.session.commit()
    return jsonify({"status": "ok"})


@bp_document.route("/api/documents/<int:document_id>/users/<int:user_id>", methods=["DELETE"])
@login_required
def api_doc_remove_user(document_id, user_id):
    document = Document.query.get_or_404(document_id)
    require_document_admin(document)
    DocumentUser.query.filter_by(document_id=document_id, user_id=user_id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# JSON list of documents in a project (for ingestion wizard)
# -------------------------

@bp_document.route("/api/projects/<int:project_id>/documents")
@login_required
def api_project_documents(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.user_has_access(current_user):
        abort(403)

    docs = Document.query.filter_by(project_id=project_id).order_by(Document.name).all()

    accessible = [d for d in docs if d.user_has_access(current_user)]
    return jsonify([{"id": d.id, "name": d.name, "language": d.language} for d in accessible])


# -------------------------
# TEI export of full document
# -------------------------

@bp_document.route("/documents/<int:document_id>/export")
@requires_access(Document, 'document_id')
def document_export_tei(document: Document):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    parts = [f'<body n="{document.name}">']
    for page in document.pages:
        page_tei = build_tei_from_annotations(page.full_text, page.annotations or [], users_by_id=users_by_id)
        parts.append(f'<ab n="{page.label}">')
        parts.append(page_tei)
        parts.append('</ab>')
    parts.append('</body>')
    tei_body = "\n".join(parts)
    return Response(tei_body, mimetype="text/xml",
                    headers={"Content-Disposition": f'attachment; filename="{document.name}.xml"'})


# -------------------------
# ZIP download of full document (TEI + annotations JSON per page)
# -------------------------

@bp_document.route("/documents/<int:document_id>/download")
@requires_access(Document, 'document_id')
def document_download_zip(document: Document):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for page in document.pages:
            safe_label = page.label.replace("/", "_").replace("\\", "_")
            tei = build_tei_from_annotations(page.full_text, page.annotations or [], users_by_id=users_by_id)
            zf.writestr(f"{safe_label}.xml", tei)
            zf.writestr(f"{safe_label}.json", json.dumps(page.annotations or [], ensure_ascii=False, indent=2))
    buf.seek(0)
    safe_name = document.name.replace("/", "_").replace("\\", "_")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'},
    )


# -------------------------
# Works CRUD
# -------------------------

@bp_document.route("/api/documents/<int:document_id>/works", methods=["POST"])
@requires_access(Document, 'document_id')
def api_doc_add_work(document: Document):
    require_document_admin(document)
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400)
    genre = (data.get("genre") or "").strip() or None
    work = Work(title=title, genre=genre)
    db.session.add(work)
    db.session.flush()
    db.session.add(DocumentWork(document_id=document.id, work_id=work.id))
    db.session.commit()
    return jsonify({"status": "ok", "work": {"id": work.id, "title": work.title, "genre": work.genre}})


@bp_document.route("/api/documents/<int:document_id>/works/<int:work_id>", methods=["DELETE"])
@requires_access(Document, 'document_id')
def api_doc_remove_work(document: Document, work_id):
    require_document_admin(document)
    DocumentWork.query.filter_by(document_id=document.id, work_id=work_id).delete()
    # Delete orphaned Work
    if not DocumentWork.query.filter_by(work_id=work_id).count():
        Work.query.filter_by(id=work_id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})
