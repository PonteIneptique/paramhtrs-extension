import io
import json
import os
import zipfile

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, Response
from flask_login import login_required, current_user
from .models import db, Folder, FolderUser, Work, Project, Document, Line, User
from .bp_auth import requires_access
from .annot_utils import build_tei_from_annotations, build_tei_header, document_metadata

bp_folder = Blueprint(
    "bp_folder", __name__,
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


def require_folder_admin(folder: Folder):
    """Abort 403 unless the current user is a site admin, the project creator,
    or the folder creator."""
    project = Project.query.get(folder.project_id)
    if not (
        current_user.is_admin
        or project.creator_id == current_user.id
        or folder.creator_id == current_user.id
    ):
        abort(403)


# -------------------------
# Create folder
# -------------------------

@bp_folder.route("/folders/new", methods=["GET", "POST"])
@login_required
def folder_create():
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

        folder = Folder(
            name=data.get("name", "Untitled"),
            description=data.get("description", ""),
            project_id=project_id,
            creator_id=current_user.id,
        )
        folder.language = data.get("language", "fre")
        if data.get("qid"):
            folder.qid = data.get("qid")
        db.session.add(folder)
        db.session.commit()

        if request.is_json:
            return jsonify({"status": "ok", "id": folder.id, "name": folder.name})
        flash("Folder created", "success")
        return redirect(url_for("bp_folder.folder_browse", folder_id=folder.id))

    # GET — show form
    project_id = request.args.get("project_id", type=int)
    project = None
    if project_id:
        project = Project.query.get_or_404(project_id)
        if not project.user_has_access(current_user):
            abort(403)
    return render_template("folders/new.html", project=project, languages=LANGUAGES)


# -------------------------
# Browse folder (list documents)
# -------------------------

@bp_folder.route("/folders/<int:folder_id>")
@requires_access(Folder, 'folder_id')
def folder_browse(folder: Folder):
    from sqlalchemy.orm import joinedload
    from .stats_report import page_validation_counts
    from .models import Part
    documents = (Document.query.filter_by(folder_id=folder.id)
              .options(joinedload(Document.annotation_rows),
                       joinedload(Document.parts).joinedload(Part.metadata_))
              .order_by(Document.order).all())
    page_validation = {document.id: page_validation_counts(document) for document in documents}
    processing = {}
    for document in documents:
        job = document.active_job
        if job and job.status != "done":
            processing[document.id] = {
                "status": job.status, "current": job.processed_chunks, "total": job.total_chunks,
            }
    can_edit = (
        current_user.is_admin
        or Project.query.get(folder.project_id).creator_id == current_user.id
        or folder.creator_id == current_user.id
    )
    return render_template(
        "folders/edit.html",
        document=folder,
        pages=documents,
        page_validation=page_validation,
        processing=processing,
        can_edit=can_edit,
        languages=LANGUAGES,
        works=[{"id": w.id, "title": w.title, "genre": w.genre} for w in folder.works],
    )


# -------------------------
# Edit folder metadata
# -------------------------

@bp_folder.route("/folders/<int:folder_id>/edit", methods=["POST"])
@requires_access(Folder, 'folder_id')
def folder_update(folder: Folder):
    require_folder_admin(folder)
    data = request.json if request.is_json else request.form
    if "name" in data:
        folder.name = data.get("name") or folder.name
    if "description" in data:
        folder.description = data.get("description", folder.description)
    if "language" in data:
        folder.language = data.get("language", folder.language)
    if "qid" in data:
        folder.qid = data.get("qid") or None
    if "iiif_manifest_url" in data:
        folder.iiif_manifest_url = data.get("iiif_manifest_url") or None
    db.session.commit()
    if request.is_json:
        return jsonify({"status": "ok"})
    flash("Folder updated", "success")
    return redirect(url_for("bp_folder.folder_browse", folder_id=folder.id))


# -------------------------
# Delete folder
# -------------------------

@bp_folder.route("/folders/<int:folder_id>/delete")
@requires_access(Folder, 'folder_id')
def folder_delete(folder: Folder):
    require_folder_admin(folder)
    if request.args.get("confirm", type=bool, default=False):
        project_id = folder.project_id
        db.session.delete(folder)
        db.session.commit()
        flash("Folder deleted", "success")
        return redirect(url_for("bp_project.project_browse", project_id=project_id))
    return render_template("folders/delete.html", document=folder)


# -------------------------
# Manage folder users
# -------------------------

@bp_folder.route("/folders/<int:folder_id>/users")
@login_required
def folder_users(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    require_folder_admin(folder)
    users = User.query.order_by(User.username).all()
    folder_user_ids = {u.id for u in folder.users}
    return render_template(
        "folders/users.html",
        document=folder,
        users=users,
        document_user_ids=folder_user_ids,
    )


@bp_folder.route("/api/folders/<int:folder_id>/users")
@login_required
def api_folder_users(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    require_folder_admin(folder)
    return jsonify({
        "folder_id": folder.id,
        "users": [
            {"id": u.id, "username": u.username, "has_access": folder.user_has_access(u)}
            for u in User.query.all()
        ],
    })


@bp_folder.route("/api/folders/<int:folder_id>/users/<int:user_id>", methods=["POST"])
@login_required
def api_folder_add_user(folder_id, user_id):
    folder = Folder.query.get_or_404(folder_id)
    require_folder_admin(folder)
    if folder.creator_id == user_id:
        abort(400)
    exists = FolderUser.query.filter_by(folder_id=folder_id, user_id=user_id).first()
    if not exists:
        db.session.add(FolderUser(folder_id=folder_id, user_id=user_id))
        db.session.commit()
    return jsonify({"status": "ok"})


@bp_folder.route("/api/folders/<int:folder_id>/users/<int:user_id>", methods=["DELETE"])
@login_required
def api_folder_remove_user(folder_id, user_id):
    folder = Folder.query.get_or_404(folder_id)
    require_folder_admin(folder)
    FolderUser.query.filter_by(folder_id=folder_id, user_id=user_id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# JSON list of folders in a project (for ingestion wizard)
# -------------------------

@bp_folder.route("/api/projects/<int:project_id>/folders")
@login_required
def api_project_folders(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.user_has_access(current_user):
        abort(403)

    folders = Folder.query.filter_by(project_id=project_id).order_by(Folder.name).all()

    accessible = [f for f in folders if f.user_has_access(current_user)]
    return jsonify([{"id": f.id, "name": f.name, "language": f.language} for f in accessible])


# -------------------------
# Reorder documents within a folder
# -------------------------

@bp_folder.route("/api/folders/<int:folder_id>/documents/reorder", methods=["POST"])
@requires_access(Folder, 'folder_id')
def api_folder_reorder_documents(folder: Folder):
    order = (request.json or {}).get("order") or []
    documents_by_id = {d.id: d for d in Document.query.filter_by(folder_id=folder.id).all()}
    if set(order) != set(documents_by_id.keys()):
        abort(400)
    for idx, document_id in enumerate(order):
        documents_by_id[document_id].order = idx
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Bulk background-normalization progress for every document in a folder
# (one request for the whole browse list, polled while any row is processing)
# -------------------------

@bp_folder.route("/api/folders/<int:folder_id>/processing-status")
@requires_access(Folder, 'folder_id')
def api_folder_processing_status(folder: Folder):
    result = {}
    for document in folder.documents:
        job = document.active_job
        if job is None or job.status == "done":
            continue
        result[document.id] = {
            "status": job.status,
            "current": job.processed_chunks,
            "total": job.total_chunks,
            "error": job.error,
        }
    return jsonify(result)


# -------------------------
# TEI export of full folder
# -------------------------

@bp_folder.route("/folders/<int:folder_id>/stats")
@requires_access(Folder, 'folder_id')
def folder_stats(folder: Folder):
    from .stats_report import compute_stats, build_chart_svg, load_font_face, today_str
    stats = compute_stats(folder.documents)
    html = render_template('stats_report.html',
        title=folder.name,
        stats=stats,
        chart_svg=build_chart_svg(stats),
        font_face=load_font_face(),
        generated=today_str(),
        scope='document',
    )
    return Response(html, mimetype='text/html',
                    headers={'Content-Disposition': f'attachment; filename="stats-{folder.name}.html"'})


@bp_folder.route("/folders/<int:folder_id>/export")
@requires_access(Folder, 'folder_id')
def folder_export_tei(folder: Folder):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}

    corpus_meta = {
        "document": folder.name,
        "language": folder.language,
        "qid": folder.qid,
        "works": [{"title": w.title, "genre": w.genre} for w in folder.works],
    }
    corpus_header = build_tei_header(corpus_meta, users_by_id=users_by_id)

    document_teis = [
        build_tei_from_annotations(document.full_text, document.annotations or [], users_by_id=users_by_id,
                                    metadata=document_metadata(document), lines=document.line_offsets,
                                    subparts=document.part_offsets)
        for document in folder.documents
    ]

    tei_corpus = (
        '<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">\n'
        f'{corpus_header}\n'
        + "\n".join(document_teis)
        + '\n</teiCorpus>'
    )
    return Response(tei_corpus, mimetype="text/xml",
                    headers={"Content-Disposition": f'attachment; filename="{folder.name}.xml"'})


# -------------------------
# ZIP download of full folder (TEI + annotations JSON per document)
# -------------------------

@bp_folder.route("/folders/<int:folder_id>/download")
@requires_access(Folder, 'folder_id')
def folder_download_zip(folder: Folder):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for document in folder.documents:
            safe_label = document.label.replace("/", "_").replace("\\", "_")
            tei = build_tei_from_annotations(document.full_text, document.annotations or [], users_by_id=users_by_id,
                                              metadata=document_metadata(document), lines=document.line_offsets,
                                              subparts=document.part_offsets)
            zf.writestr(f"{safe_label}.xml", tei)
            zf.writestr(f"{safe_label}.json", json.dumps(document.annotations or [], ensure_ascii=False, indent=2))
            zf.writestr(f"{safe_label}_source.txt", document.full_text)
    buf.seek(0)
    safe_name = folder.name.replace("/", "_").replace("\\", "_")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'},
    )


# -------------------------
# Works CRUD
# -------------------------

@bp_folder.route("/api/folders/<int:folder_id>/works", methods=["POST"])
@requires_access(Folder, 'folder_id')
def api_folder_add_work(folder: Folder):
    require_folder_admin(folder)
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400)
    genre = (data.get("genre") or "").strip() or None
    work = Work(title=title, genre=genre)
    db.session.add(work)
    db.session.flush()
    folder.add_work(work)
    db.session.commit()
    return jsonify({"status": "ok", "work": {"id": work.id, "title": work.title, "genre": work.genre}})


@bp_folder.route("/api/folders/<int:folder_id>/works/<int:work_id>", methods=["DELETE"])
@requires_access(Folder, 'folder_id')
def api_folder_remove_work(folder: Folder, work_id):
    require_folder_admin(folder)
    folder.remove_work(work_id)
    db.session.commit()
    return jsonify({"status": "ok"})
