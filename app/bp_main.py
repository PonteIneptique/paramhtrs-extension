import json

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
import os
import lxml.etree as et

from .models import db, Line

bp_main = Blueprint("bp_main", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path='')

# -------------------------
# Flask routes
# -------------------------
@bp_main.route("/")
def index_route():
    # lines = Line.query.all()
    return render_template("index.html")

@bp_main.route("/lines")
def lines_list_route():
    search_query = request.args.get('search', '')
    hide_query = request.args.get('hide', 0, type=int)

    query = Line.query
    if search_query:
        query = query.filter(Line.original_text.like("%" + search_query + "%"))

    query = query.paginate(page=request.args.get("page", type=int, default=1),
                        per_page=request.args.get("per_page", type=int, default=20))

    return render_template(
        "lines.html",
        search_query=search_query,
        hide=hide_query,
        lines=query.items,
        pagination=query
    )

@bp_main.route("/normalize", methods=["POST"])
def normalize_route():
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


@bp_main.route("/lines/new", methods=["POST", "GET"])
def new_line_route():
    if request.method == "POST":
        from .process import normalize_line, get_model_and_tokenizer, align_to_segs
        form = request.json
        metadata = {key: value for key, value in form.items() if key != 'lines'}

        results = []

        for line in form["lines"]:
            results.append({
                "input": line["orig"],
                "normalized": line["reg"],
                "xml": align_to_segs(line["orig"], line["reg"])
            })
        for r in results:
            db.session.add(Line(original_text=r["input"], xml=r["xml"], status="pending",
                                metadata_json=json.dumps(metadata)))
        db.session.commit()
        flash("Successfully created a new line!", "success")
        return redirect(url_for("bp_main.lines_list_route"))

    # GET
    return render_template("create.html")


@bp_main.route("/lines/<int:line_id>", methods=["POST", "GET"])
def line_route(line_id):
    line = Line.query.get_or_404(line_id)
    if request.args.get("format") == "tei":
        from .process import from_xml_to_tei
        return from_xml_to_tei(line.xml)
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

        line.xml = align_to_segs(source, normz)
        line.status = data.get("status", line.status)
        db.session.add(line)
        db.session.commit()
        return jsonify({"status": "ok", "updatedLine": {
            "id": line.id,
            "original_text": line.original_text,
            "metadata_json": json.loads(line.metadata_json),
            "xml": line.xml,
            "status": line.status
        }})
    else:
        return render_template(
            "line.html",
            line={
                "xml": line.xml,
                "original_text": line.original_text,
            "metadata_json": json.loads(line.metadata_json),
                "id": line.id,
                "status": line.status
            }
        )

@bp_main.route("/save", methods=["POST"])
def save_line():
    data = request.json
    line_id = data["id"]
    xml = data["xml"]
    line = Line.query.get(line_id)
    if line:
        line.xml = xml
        db.session.commit()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 404