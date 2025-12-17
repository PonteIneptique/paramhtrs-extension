from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)
import os
from .models import Project, db, Normalization

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
@bp_project.route("/projects/new", methods=["GET", "POST"])
def project_create():
    if request.method == "POST":
        name = request.form["name"]
        description = request.form.get("description", "")

        project = Project(name=name, description=description)
        db.session.add(project)
        db.session.commit()

        flash("Project created", "success")
        return redirect(url_for("bp_project.project_browse", project_id=project.id))

    return render_template("projects/new.html")

@bp_project.route("/projects/<int:project_id>", methods=["GET"])
def project_browse(project_id):
    project = Project.query.get_or_404(project_id)

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
        "projects/browse.html",
        project=project,
        pagination=pagination,
        search=search,
    )

@bp_project.route("/projects/<int:project_id>/edit", methods=["POST"])
def project_update(project_id):
    project = Project.query.get_or_404(project_id)

    project.name = request.form["name"]
    project.description = request.form.get("description", "")

    db.session.commit()
    flash("Project updated", "success")

    return redirect(url_for("bp_project.project_browse", project_id=project.id))

@bp_project.route("/projects/<int:project_id>/delete", methods=["GET"])
def project_delete(project_id):
    project = Project.query.get_or_404(project_id)

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

    projects = query.order_by(Project.name).all()

    if request.args.get("format", default=None, type=str) == "json":
        return jsonify([
            {"id": project.id, "name": project.name}
            for project in projects
        ])
    return render_template("projects/list.html", projects=projects)
