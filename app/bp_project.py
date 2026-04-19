import io
import json
import os
import zipfile

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify,
    Response,
)
from sqlalchemy import or_
from flask_login import login_required, current_user
from .models import Project, Document, db, User, ProjectUser
from .bp_auth import requires_access
from .annot_utils import build_tei_from_annotations, page_metadata

bp_project = Blueprint(
    "bp_project",
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "template"
    ),
    static_folder=os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "static"
    ),
    static_url_path="",
)


def require_project_admin(project: Project):
    if not (current_user.is_admin or project.creator_id == current_user.id):
        abort(403)


@bp_project.route("/projects/new", methods=["GET", "POST"])
@login_required
def project_create():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")
        project = Project(name=name, description=description, creator_id=current_user.id)
        db.session.add(project)
        db.session.commit()
        flash("Project created", "success")
        return redirect(url_for("bp_project.project_browse", project_id=project.id))
    return render_template("projects/new.html")


@bp_project.route("/projects/<int:project_id>", methods=["GET"])
@requires_access(Project, 'project_id')
def project_browse(project: Project):
    search = request.args.get("search", "").strip()
    documents = Document.query.filter_by(project_id=project.id)
    if search:
        documents = documents.filter(Document.name.ilike(f"%{search}%"))
    documents = documents.order_by(Document.name).all()

    return render_template(
        "projects/edit.html",
        project=project,
        documents=documents,
        search=search,
        can_edit=(current_user.is_admin or project.creator_id == current_user.id)
    )


@bp_project.route("/projects/<int:project_id>/edit", methods=["POST"])
@requires_access(Project, 'project_id')
def project_update(project: Project):
    project.name = request.form["name"]
    project.description = request.form.get("description", "")
    db.session.commit()
    flash("Project updated", "success")
    return redirect(url_for("bp_project.project_browse", project_id=project.id))


@bp_project.route("/projects/<int:project_id>/delete", methods=["GET"])
@requires_access(Project, 'project_id')
def project_delete(project: Project):
    if request.args.get("confirm", type=bool, default=False):
        db.session.delete(project)
        db.session.commit()
        flash("Successfully deleted project!", "success")
        return redirect(url_for("bp_project.project_lists"))
    return render_template("projects/delete.html", project=project)


@bp_project.route("/projects", methods=["GET"])
@login_required
def project_lists():
    search = request.args.get("search", "").strip()
    query = Project.query
    if search:
        query = query.filter(Project.name.ilike(f"%{search}%"))

    query = query.outerjoin(Project.users).filter(
        or_(
            Project.creator_id == current_user.id,
            Project.users.any(id=current_user.id)
        )
    )

    if request.args.get("format") == "json":
        return jsonify([{"id": p.id, "name": p.name} for p in query])
    return render_template("projects/list.html", projects=query)


@bp_project.route("/projects/<int:project_id>/users")
@login_required
def project_users(project_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)
    users = User.query.order_by(User.username).all()
    project_user_ids = {u.id for u in project.users}
    return render_template(
        "projects/users.html",
        project=project,
        users=users,
        project_user_ids=project_user_ids,
    )


@bp_project.route("/projects/<int:project_id>/download")
@requires_access(Project, 'project_id')
def project_download_zip(project: Project):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for document in Document.query.filter_by(project_id=project.id).order_by(Document.name).all():
            if not document.user_has_access(current_user):
                continue
            safe_doc = document.name.replace("/", "_").replace("\\", "_")
            for page in document.pages:
                safe_label = page.label.replace("/", "_").replace("\\", "_")
                tei = build_tei_from_annotations(page.full_text, page.annotations or [], users_by_id=users_by_id, metadata=page_metadata(page))
                zf.writestr(f"{safe_doc}/{safe_label}.xml", tei)
                zf.writestr(f"{safe_doc}/{safe_label}.json", json.dumps(page.annotations or [], ensure_ascii=False, indent=2))
                zf.writestr(f"{safe_doc}/{safe_label}_source.txt", page.full_text)
    buf.seek(0)
    safe_name = project.name.replace("/", "_").replace("\\", "_")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'},
    )


@bp_project.route("/api/projects/<int:project_id>/users")
@login_required
def api_project_users(project_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)
    return jsonify({
        "project_id": project.id,
        "users": [
            {"id": u.id, "username": u.username, "has_access": project.user_has_access(u)}
            for u in User.query.all()
        ],
    })


@bp_project.route("/api/projects/<int:project_id>/users/<int:user_id>", methods=["POST"])
@login_required
def api_add_user(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)
    if project.creator_id == user_id:
        abort(400)
    exists = ProjectUser.query.filter_by(project_id=project_id, user_id=user_id).first()
    if not exists:
        db.session.add(ProjectUser(project_id=project_id, user_id=user_id))
        db.session.commit()
    return jsonify({"status": "ok"})


@bp_project.route("/api/projects/<int:project_id>/users/<int:user_id>", methods=["DELETE"])
@login_required
def api_remove_user(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)
    ProjectUser.query.filter_by(project_id=project_id, user_id=user_id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})
