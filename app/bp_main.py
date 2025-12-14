from flask import Blueprint, render_template, request, jsonify
import os

from sympy.codegen.ast import continue_

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

@bp_main.route("/lines/<int:line_id>")
def line_route(line_id):
    line = Line.query.get_or_404(line_id)
    return render_template(
        "line.html",
        line={
            "xml": line.xml,
            "original_text": line.original_text,
            "id": line.id
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