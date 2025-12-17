import json

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response
import os
import lxml.etree as et

from .models import db, Normalization

bp_main = Blueprint("bp_main", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path='')

# -------------------------
# Flask routes
# -------------------------
@bp_main.route("/")
def index_route():
    return render_template("index.html")

@bp_main.route("/normalizations")
def normalization_list_route():
    search_query = request.args.get('search', '')
    current_filter = request.args.get('filter', 'all', type=str)

    query = Normalization.query
    if search_query:
        query = query.filter(Normalization.original_text.like("%" + search_query + "%"))

    if current_filter in {'pending', 'active', 'done'}:
        query = query.filter(Normalization.status == current_filter)

    if request.args.get("download", default=None, type=str):
        return jsonify(
            [normalization.json_compatible for normalization in query.all()]
        )

    query = query.paginate(page=request.args.get("page", type=int, default=1),
                        per_page=request.args.get("per_page", type=int, default=20))

    return render_template(
        "normalization_list.html",
        search_query=search_query,
        normalizations=query.items,
        pagination=query,
        current_filter=current_filter
    )

@bp_main.route("/normalizations/process", methods=["POST"])
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


@bp_main.route("/normalizations/new", methods=["POST", "GET"])
def normalization_new_route():
    if request.method == "POST":
        from .process import align_to_segs
        form = request.json
        metadata = {key: value for key, value in form.items() if key != 'lines'}

        results = []

        for normalization in form["normalizations"]:
            results.append({
                "input": normalization["orig"],
                "normalized": normalization["reg"],
                "xml": align_to_segs(normalization["orig"], normalization["reg"])
            })
        for r in results:
            db.session.add(Normalization(original_text=r["input"], xml=r["xml"], status="pending",
                                         metadata_json=json.dumps(metadata), project_id=form["project_id"]))
        db.session.commit()
        flash("Successfully created a new line!", "success")
        return redirect(url_for("bp_main.normalization_list_route"))

    # GET
    return render_template("normalization_create.html")

@bp_main.route("/normalizations/<int:normalization_id>/delete", methods=["GET"])
def normalization_delete_route(normalization_id):
    normalization = Normalization.query.get(normalization_id)
    if request.args.get("confirm", type=bool, default=False):
        db.session.delete(normalization)
        db.session.commit()
        flash("Successfully deleted line!", "success")
        return redirect(url_for("bp_main.normalization_list_route"))
    return render_template("normalization_delete.html", normalization=normalization)

@bp_main.route("/normalizations/<int:normalization_id>", methods=["POST", "GET"])
def normalization_edit_route(normalization_id):
    normalization = Normalization.query.get_or_404(normalization_id)
    if request.args.get("format") == "tei":
        from .process import from_xml_to_tei
        return Response(str(from_xml_to_tei(normalization.xml)), mimetype="text/xml")
    if request.method == "POST":
        from .process import align_to_segs
        data = request.json
        # Recompute alignment
        source = ""
        normz = ""
        for seg in et.fromstring(data["xml"]).xpath("//seg"):
            origElem = seg.xpath("./orig")
            regElem = seg.xpath("./reg")
            if origElem:
                source += origElem[0].text

            # If reg is not present, we keep orig
            # However, if reg is empty, we map to an empty string
            if regElem:
                normz += regElem[0].text or ''
            else:
                normz += origElem[0].text

        normalization.xml = align_to_segs(source, normz)
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
            "normalization_edit.html",
            normalization={
                "xml": normalization.xml,
                "original_text": normalization.original_text,
                "metadata_json": json.loads(normalization.metadata_json),
                "id": normalization.id,
                "status": normalization.status
            }
        )

