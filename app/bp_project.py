import json

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify
)
from sqlalchemy import or_
from flask_login import login_required, current_user
import os
from .models import Project, db, Normalization, User, ProjectUser
from .bp_auth import requires_access
from .alignment import align_and_markup

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
    if not (
        current_user.is_admin
        or project.creator_id == current_user.id
    ):
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
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 50)
    search = request.args.get("search", "")

    norms_query = db.session.query(Normalization).filter(Normalization.id == project.id)

    if search:
        norms_query = norms_query.filter(
            Normalization.original_text.ilike(f"%{search}%")
        )

    pagination = norms_query.order_by(Normalization.id).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    return render_template(
        "projects/edit.html",
        project=project,
        pagination=pagination,
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

    return render_template(
        "projects/project_delete.html",
        project=project,
    )


@bp_project.route("/projects", methods=["GET"])
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

    if request.args.get("format", default=None, type=str) == "json":
        return jsonify([
            {"id": project.id, "name": project.name}
            for project in query
        ])
    return render_template("projects/list.html", projects=query)

@bp_project.route("/projects/<int:project_id>/users")
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

@bp_project.route("/projects/<int:project_id>/upload")
def project_upload(project_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)

    return render_template(
        "projects/upload.html",
        project=project,
    )

@bp_project.route("/api/projects/<int:project_id>/users")
def api_project_users(project_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)

    return {
        "project_id": project.id,
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "has_access": project.user_has_access(u),
            }
            for u in User.query.all()
        ],
    }

@bp_project.route("/api/projects/<int:project_id>/users/<int:user_id>", methods=["POST"])
def api_add_user(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)

    if project.creator_id == user_id:
        abort(400)

    exists = ProjectUser.query.filter_by(
        project_id=project_id,
        user_id=user_id,
    ).first()

    if not exists:
        db.session.add(ProjectUser(
            project_id=project_id,
            user_id=user_id,
        ))
        db.session.commit()

    return {"status": "ok"}

@bp_project.route("/api/projects/<int:project_id>/users/<int:user_id>", methods=["DELETE"])
def api_remove_user(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)

    ProjectUser.query.filter_by(
        project_id=project_id,
        user_id=user_id,
    ).delete()

    db.session.commit()
    return {"status": "ok"}


@bp_project.route("/api/projects/<int:project_id>/upload", methods=["POST"])
@login_required
def api_project_upload(project_id):
    project = Project.query.get_or_404(project_id)
    require_project_admin(project)

    data = request.get_json(force=True)

    source = data.get("source")
    target = data.get("target")

    if not source or not target:
        return jsonify({"error": "Missing source or target"}), 400

    # example XML stub
    xml = align_and_markup(source, target)

    norm = Normalization.query.filter_by(
        original_text=source,
        project_id=project.id
    ).first()

    if norm:
        norm.metadata_json = {"updated": True}
    else:
        metadata = {
            k: v for k, v in data.items()
            if k not in {"source", "target"}
        }
        norm = Normalization(
            original_text=source,
            xml=xml,
            project_id=project.id,
            metadata_json=json.dumps(metadata),
            status='pending'
        )
        db.session.add(norm)

    db.session.commit()

    return jsonify({"status": "ok"})
