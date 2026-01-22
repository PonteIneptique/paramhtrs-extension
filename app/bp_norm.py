import json

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response, abort
from sqlalchemy import or_, and_
from flask_login import login_required, current_user
import os
import lxml.etree as et

def validate_xml(xml: str) -> tuple[bool, str | None]:
    try:
        et.fromstring(xml.encode("utf-8"))
        return True, None
    except et.XMLSyntaxError as e:
        return False, str(e)

from .models import db, Normalization, Project
from .bp_auth import requires_access
from .aligner import align_and_markup

bp_norm = Blueprint("bp_norm", __name__,
                    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
                    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
                    static_url_path='')

# -------------------------
# Flask routes
# -------------------------

@bp_norm.route("/projects/<int:project_id>/normalizations")
@login_required
@requires_access(Project, 'project_id')
def normalization_list_route(project: Project):
    search_query = request.args.get('search', '')
    current_filter = request.args.get('filter', 'all', type=str)
    # combination
    data = [(Normalization.project_id == project.id)]
    if search_query:
        data.append(Normalization.original_text.like("%" + search_query + "%"))

    if current_filter in {'pending', 'active', 'done'}:
        data.append((Normalization.status == current_filter))
    query = Normalization.query.filter(and_(*data))

    if request.args.get("download", default=None, type=str):
        return jsonify(
            [normalization.json_compatible for normalization in query.all()]
        )

    query = query.paginate(page=request.args.get("page", type=int, default=1),
                        per_page=request.args.get("per_page", type=int, default=20))

    return render_template(
        "normalization/list.html",
        search_query=search_query,
        normalizations=query.items,
        pagination=query,
        current_filter=current_filter, project_id=project.id
    )

@bp_norm.route("/normalizations/process", methods=["POST"])
@login_required
def normalization_process_route():
    from .process import normalize_line, get_model_and_tokenizer
    model, tokenizer = get_model_and_tokenizer()
    data = request.json
    results = []
    for raw_line in data.get("inputtext").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = normalize_line(line, model, tokenizer)
        results.append({
            "orig": line,
            "reg": normalized
        })
    return jsonify(results)


@bp_norm.route("/normalizations/new", methods=["POST", "GET"])
@login_required
def normalization_new_route():
    if request.method == "POST":
        form = request.json
        project = Project.query.get_or_404(form["project_id"])
        if not project.user_has_access(current_user):
            abort(403)
        metadata = {key: value for key, value in form.items() if key != 'normalizations'}

        results = []

        for normalization in form["normalizations"]:
            results.append({
                "input": normalization["orig"],
                "normalized": normalization["reg"],
                "xml": align_and_markup(normalization["orig"], normalization["reg"])
            })
        for r in results:
            db.session.add(Normalization(original_text=r["input"], xml=r["xml"], status="pending",
                                         metadata_json=json.dumps(metadata), project_id=form["project_id"]))
        db.session.commit()
        flash("Successfully created a new line!", "success")
        return jsonify({
            "status": "success",
            "redirect": url_for("bp_norm.normalization_list_route", project_id=project.id)
        })

    if request.args.get("project_id"):
        project = Project.query.get(request.args.get("project_id", type=int))
        if not project:
            abort(403)
        if project.user_has_access(current_user):
            return render_template('normalization/create.html', project=project)

    # GET
    return render_template("normalization/create.html")

@bp_norm.route("/normalizations/<int:normalization_id>/delete", methods=["GET"])
@requires_access(Normalization, 'normalization_id')
def normalization_delete_route(normalization: Normalization):
    if request.args.get("confirm", type=bool, default=False):
        db.session.delete(normalization)
        db.session.commit()
        flash("Successfully deleted line!", "success")
        return redirect(url_for("bp_norm.normalization_list_route"))
    return render_template("normalization/delete.html", normalization=normalization)

@bp_norm.route("/normalizations/<int:normalization_id>", methods=["POST", "GET"])
@requires_access(Normalization, 'normalization_id')
def normalization_edit_route(normalization: Normalization):
    if request.args.get("format") == "tei":
        from .process import from_xml_to_tei
        return Response(str(from_xml_to_tei(normalization.xml)), mimetype="text/xml")
    if request.method == "POST":
        data = request.json
        # Recompute alignment
        source = ""
        normz = ""
        for seg in data["json"]:
            origElem = seg.get("orig")
            regElem = seg.get("reg")
            if origElem is not None:
                source += origElem

            # If reg is not present, we keep orig
            # However, if reg is empty, we map to an empty string
            if regElem is not None:
                normz += regElem or ''
            else:
                normz += origElem

        normalization.xml = align_and_markup(source, normz)
        normalization.status = data.get("status", normalization.status)
        db.session.add(normalization)
        db.session.commit()
        return jsonify({"status": "ok", "content": {
            "id": normalization.id,
            "original_text": normalization.original_text,
            "metadata_json": json.loads(normalization.metadata_json),
            "xml": normalization.xml,
            "status": normalization.status
        }})
    else:
        return render_template(
            "normalization/edit.html",
            normalization={
                "xml": normalization.xml,
                "original_text": normalization.original_text,
                "metadata_json": json.loads(normalization.metadata_json),
                "id": normalization.id,
                "status": normalization.status
            }
        )

@bp_norm.route("/normalizations/<int:normalization_id>/edit-xml", methods=["GET", "POST"])
@requires_access(Normalization, 'normalization_id')
def edit_normalization(normalization):
    error = None

    if request.method == "POST":
        raw_xml = request.form.get("xml", "")

        # remove UI formatting
        cleaned_xml = raw_xml.replace("</seg>\n", "</seg>")

        is_valid, error = validate_xml(cleaned_xml)

        if is_valid:
            normalization.xml = cleaned_xml
            db.session.commit()
            return redirect(url_for(".edit_normalization", norm_id=norm.id))

    return render_template(
        "normalization/xml.html",
        normalization=normalization
    )
