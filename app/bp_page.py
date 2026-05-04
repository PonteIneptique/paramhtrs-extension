import os

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, Response
from flask_login import login_required, current_user
from sqlalchemy import func

from .models import db, Page, Line, Document, Project, User, Work, PageWork, DocumentWork
from .bp_auth import requires_access
from .annot_utils import align_to_annotations, align_to_annotations_from_chunks, build_tei_from_annotations, page_metadata

bp_page = Blueprint(
    "bp_page", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path=''
)


# -------------------------
# Create page + lines atomically (called from ingestion wizard)
# -------------------------

@bp_page.route("/pages/new", methods=["GET", "POST"])
@login_required
def page_create():
    if request.method == "POST":
        data = request.json
        document_id = data.get("document_id")
        document = Document.query.get_or_404(document_id)
        if not document.user_has_access(current_user):
            abort(403)

        label = data.get("label", "").strip() or "Page 1"

        max_order = db.session.query(func.max(Page.order)).filter_by(document_id=document_id).scalar()
        next_order = (max_order or 0) + 1

        page = Page(document_id=document_id, label=label, order=next_order, status="pending")
        db.session.add(page)
        db.session.flush()

        orig_lines = []
        for idx, entry in enumerate(data.get("lines", [])):
            orig = entry.get("orig", "").strip()
            if not orig:
                continue
            line = Line(
                page_id=page.id,
                order=idx,
                original_text=orig,
                alto_id=entry.get("alto_id") or None,
            )
            db.session.add(line)
            orig_lines.append(orig)

        db.session.flush()

        chunks = data.get("chunks")
        separator = data.get("separator", "\n")
        full_reg = (data.get("full_reg") or "").strip()
        if chunks:
            page.set_annotations(align_to_annotations_from_chunks(chunks, separator=separator))
        elif full_reg:
            full_text = "\n".join(orig_lines)
            page.set_annotations(align_to_annotations(full_text, full_reg))
        # else: no annotations — leave empty
        db.session.commit()
        return jsonify({
            "status": "ok",
            "redirect": url_for("bp_page.page_editor", page_id=page.id)
        })

    document_id = request.args.get("document_id", type=int)
    document = None
    if document_id:
        document = Document.query.get_or_404(document_id)
        if not document.user_has_access(current_user):
            abort(403)
    return render_template("pages/new.html", document=document)


# -------------------------
# Page editor — 3-panel annotation editor
# -------------------------

@bp_page.route("/pages/<int:page_id>")
@requires_access(Page, 'page_id')
def page_editor(page: Page):
    lines_data = [
        {
            "id": line.id,
            "order": line.order,
            "original_text": line.original_text,
        }
        for line in page.lines
    ]
    return render_template(
        "pages/editor.html",
        page=page,
        document=page.document,
        lines=lines_data,
        full_text=page.full_text,
        annotations=page.annotations or [],
        prev_page=page.prev,
        next_page=page.next,
        works=page.works.all(),
    )


# -------------------------
# Update page status
# -------------------------

@bp_page.route("/api/pages/<int:page_id>/status", methods=["POST"])
@requires_access(Page, 'page_id')
def api_page_status(page: Page):
    page.status = request.json.get("status", page.status)
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Update page metadata (label)
# -------------------------

@bp_page.route("/pages/<int:page_id>/edit", methods=["POST"])
@requires_access(Page, 'page_id')
def page_update(page: Page):
    page.label = request.form.get("label", page.label).strip() or page.label
    db.session.commit()
    flash("Page updated", "success")
    return redirect(url_for("bp_page.page_editor", page_id=page.id))


# -------------------------
# Delete page
# -------------------------

@bp_page.route("/pages/<int:page_id>/delete")
@requires_access(Page, 'page_id')
def page_delete(page: Page):
    if request.args.get("confirm", type=bool, default=False):
        document_id = page.document_id
        db.session.delete(page)
        db.session.commit()
        flash("Page deleted", "success")
        return redirect(url_for("bp_document.document_browse", document_id=document_id))
    return render_template("pages/delete.html", page=page)


# -------------------------
# TEI export of a single page
# -------------------------

@bp_page.route("/pages/<int:page_id>/stats")
@requires_access(Page, 'page_id')
def page_stats(page: Page):
    from .stats_report import compute_stats, build_chart_svg, load_font_face, today_str
    stats = compute_stats([page])
    html = render_template('stats_report.html',
        title=page.label,
        stats=stats,
        chart_svg=build_chart_svg(stats),
        font_face=load_font_face(),
        generated=today_str(),
        scope='page',
    )
    return Response(html, mimetype='text/html',
                    headers={'Content-Disposition': f'attachment; filename="stats-{page.label}.html"'})


@bp_page.route("/pages/<int:page_id>/export")
@requires_access(Page, 'page_id')
def page_export_tei(page: Page):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    tei = build_tei_from_annotations(page.full_text, page.annotations or [], users_by_id=users_by_id, metadata=page_metadata(page))
    return Response(
        tei,
        mimetype="text/xml",
        headers={"Content-Disposition": f'attachment; filename="{page.label}.xml"'}
    )


# -------------------------
# Page works CRUD
# -------------------------

@bp_page.route("/api/pages/<int:page_id>/works", methods=["POST"])
@requires_access(Page, 'page_id')
def api_page_add_work(page: Page):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400)
    genre = (data.get("genre") or "").strip() or None
    work = Work(title=title, genre=genre)
    db.session.add(work)
    db.session.flush()
    db.session.add(PageWork(page_id=page.id, work_id=work.id))
    db.session.commit()
    return jsonify({"status": "ok", "work": {"id": work.id, "title": work.title, "genre": work.genre}})


@bp_page.route("/api/pages/<int:page_id>/works/<int:work_id>", methods=["DELETE"])
@requires_access(Page, 'page_id')
def api_page_remove_work(page: Page, work_id):
    PageWork.query.filter_by(page_id=page.id, work_id=work_id).delete()
    if not PageWork.query.filter_by(work_id=work_id).count() and \
       not DocumentWork.query.filter_by(work_id=work_id).count():
        Work.query.filter_by(id=work_id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})
