import os

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, Response, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from .models import db, Document, Part, Line, Folder, Project, User, Work, NormalizationJob, NormalizationJobChunk
from .bp_auth import requires_access
from .annot_utils import align_to_annotations, align_to_annotations_from_chunks, build_tei_from_annotations, document_metadata
from .normalize_jobs import build_chunks, normalize_whitespace

bp_document = Blueprint(
    "bp_document", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path=''
)


def _queue_normalization_job(document: Document, parts_lines: list, data: dict) -> NormalizationJob:
    """Builds chunks from parts_lines and queues a NormalizationJob for
    worker.py to pick up. Shared by document_create's normalize=true path
    and api_document_reprocess."""
    split_mode = data.get("split_mode", "lines")
    min_words = int(data.get("min_words", 50))
    delimiters = list(data.get("delimiters", "¶;."))
    max_chunk_bytes = current_app.config["MAX_CHUNK_BYTES"]
    chunks, separator = build_chunks(parts_lines, split_mode, min_words, delimiters, max_chunk_bytes)

    job = NormalizationJob(document_id=document.id, status="queued", separator=separator)
    db.session.add(job)
    db.session.flush()
    for order, chunk in enumerate(chunks):
        db.session.add(NormalizationJobChunk(
            job_id=job.id, order=order,
            part_index=chunk["part_index"], orig=chunk["orig"],
        ))
    return job


# -------------------------
# Create document + part + lines atomically (called from ingestion wizard)
#
# Two JSON shapes are accepted:
#   - single-source: {folder_id, label, lines: [...], chunks|full_reg, separator}
#     -> one Document with a single Part holding all lines.
#   - multi-source: {folder_id, label (or "readable"), subparts: [{id, lines: [...]}], ...}
#     -> one Document with one Part per entry in "subparts" (original_filename=id),
#        annotated across the flattened, concatenated line sequence so
#        annotations can span part boundaries.
#
# Either shape may additionally set `normalize: true` (+ split_mode/min_words/
# delimiters) instead of providing chunks/full_reg/expan up front: Parts/Lines
# are created immediately (so full_text is fixed right away), but annotation
# alignment is deferred to a queued NormalizationJob picked up by worker.py —
# the model is never called inline in this request.
# -------------------------

@bp_document.route("/documents/new", methods=["GET", "POST"])
@login_required
def document_create():
    if request.method == "POST":
        data = request.json
        folder_id = data.get("folder_id")
        folder = Folder.query.get_or_404(folder_id)
        if not folder.user_has_access(current_user):
            abort(403)

        label = (data.get("label") or data.get("readable") or "").strip() or "Document 1"

        max_order = db.session.query(func.max(Document.order)).filter_by(folder_id=folder_id).scalar()
        next_order = (max_order or 0) + 1

        document = Document(folder_id=folder_id, label=label, order=next_order, status="pending")
        db.session.add(document)
        db.session.flush()

        normalize = bool(data.get("normalize"))
        flat_chunks = []  # only used for the synchronous (non-normalize) paths
        parts_lines = []  # one list of orig line-texts per Part, in order — for build_chunks

        subpart_entries = data.get("subparts")
        if subpart_entries:
            # Multi-source shape: one Part per entry, lines flattened in order
            # for alignment so annotations can land at Document-relative offsets.
            #
            # Each entry's "chunks" (if given) carries the normalization-model's
            # own batching ({"orig", "reg"} pairs, not necessarily one per Line —
            # e.g. punctuation-mode batches span several Lines) so alignment is
            # scoped to what the model actually saw, same as the single-source
            # path below. Falls back to building one chunk per Line from each
            # line entry's "expan" for callers that pre-align per line (e.g.
            # the pre-aligned JSON import, which has no separate chunks step).
            for sp_idx, entry in enumerate(subpart_entries):
                part = Part(document_id=document.id, order=sp_idx)
                part.original_filename = entry.get("id")
                db.session.add(part)
                db.session.flush()
                part_orig_lines = []
                for idx, line_entry in enumerate(entry.get("lines", [])):
                    orig = normalize_whitespace((line_entry.get("abbr") or line_entry.get("orig") or "").strip())
                    if not orig:
                        continue
                    line = Line(
                        part_id=part.id,
                        order=idx,
                        original_text=orig,
                        alto_id=line_entry.get("alto_id") or None,
                    )
                    db.session.add(line)
                    part_orig_lines.append(orig)
                    if not normalize and "chunks" not in entry:
                        flat_chunks.append({"orig": orig, "reg": line_entry.get("expan", "")})
                parts_lines.append(part_orig_lines)
                if not normalize and "chunks" in entry:
                    flat_chunks.extend(entry.get("chunks") or [])
            db.session.flush()
            separator = data.get("separator", "\n")
            if not normalize and any(c.get("reg") for c in flat_chunks):
                document.set_annotations(align_to_annotations_from_chunks(
                    flat_chunks, separator=separator, full_text=document.full_text))
        else:
            part = Part(document_id=document.id, order=0)
            if data.get("original_filename"):
                part.original_filename = data.get("original_filename")
            db.session.add(part)
            db.session.flush()

            orig_lines = []
            for idx, entry in enumerate(data.get("lines", [])):
                orig = normalize_whitespace(entry.get("orig", "").strip())
                if not orig:
                    continue
                line = Line(
                    part_id=part.id,
                    order=idx,
                    original_text=orig,
                    alto_id=entry.get("alto_id") or None,
                )
                db.session.add(line)
                orig_lines.append(orig)
            parts_lines.append(orig_lines)

            db.session.flush()

            if not normalize:
                chunks = data.get("chunks")
                separator = data.get("separator", "\n")
                full_reg = (data.get("full_reg") or "").strip()
                full_text = "\n".join(orig_lines)
                if chunks:
                    document.set_annotations(align_to_annotations_from_chunks(
                        chunks, separator=separator, full_text=full_text))
                elif full_reg:
                    document.set_annotations(align_to_annotations(full_text, full_reg))
                # else: no annotations — leave empty

        if normalize:
            _queue_normalization_job(document, parts_lines, data)

        db.session.commit()
        return jsonify({
            "status": "ok",
            "redirect": url_for("bp_document.document_editor", document_id=document.id)
        })

    folder_id = request.args.get("folder_id", type=int)
    folder = None
    if folder_id:
        folder = Folder.query.get_or_404(folder_id)
        if not folder.user_has_access(current_user):
            abort(403)
    return render_template("documents/new.html", document=folder)


# -------------------------
# Document editor — 3-panel annotation editor
# -------------------------

@bp_document.route("/documents/<int:document_id>")
@requires_access(Document, 'document_id')
def document_editor(document: Document):
    lines_data = [
        {
            "id": line.id,
            "order": line.order,
            "original_text": line.original_text,
            "part_id": part.id,
        }
        for part in document.parts
        for line in part.lines
    ]
    return render_template(
        "documents/editor.html",
        page=document,
        document=document.folder,
        lines=lines_data,
        full_text=document.full_text,
        annotations=document.annotations or [],
        part_offsets=document.part_offsets,
        prev_page=document.prev,
        next_page=document.next,
        works=[{"id": w.id, "title": w.title, "genre": w.genre} for w in document.works],
        part_works={part.id: [{"id": w.id, "title": w.title, "genre": w.genre} for w in part.works]
                    for part in document.parts},
        processing=_job_progress_dict(document.active_job),
    )


# -------------------------
# Dev-only: editor with capped annotation count for design review
# -------------------------

@bp_document.route("/dev/documents/<int:document_id>")
@requires_access(Document, 'document_id')
def document_editor_dev(document: Document):
    limit = int(request.args.get("limit", 50))
    lines_data = [
        {
            "id": line.id,
            "order": line.order,
            "original_text": line.original_text,
            "part_id": part.id,
        }
        for part in document.parts
        for line in part.lines
    ]
    return render_template(
        "documents/editor.html",
        page=document,
        document=document.folder,
        lines=lines_data,
        full_text=document.full_text,
        annotations=(document.annotations or [])[:limit],
        part_offsets=document.part_offsets,
        prev_page=document.prev,
        next_page=document.next,
        works=[{"id": w.id, "title": w.title, "genre": w.genre} for w in document.works],
        part_works={part.id: [{"id": w.id, "title": w.title, "genre": w.genre} for w in part.works]
                    for part in document.parts},
        processing=_job_progress_dict(document.active_job),
    )


# -------------------------
# Update a part's metadata (id/original_filename, qid)
# -------------------------

@bp_document.route("/api/parts/<int:part_id>/edit", methods=["POST"])
@requires_access(Part, 'part_id')
def api_part_update(part: Part):
    data = request.json or {}
    if "original_filename" in data:
        part.original_filename = (data.get("original_filename") or "").strip() or None
    if "qid" in data:
        part.qid = (data.get("qid") or "").strip() or None
    db.session.commit()
    return jsonify({"status": "ok", "original_filename": part.original_filename, "qid": part.qid})


# -------------------------
# Part works CRUD
# -------------------------

@bp_document.route("/api/parts/<int:part_id>/works", methods=["POST"])
@requires_access(Part, 'part_id')
def api_part_add_work(part: Part):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400)
    genre = (data.get("genre") or "").strip() or None
    work = Work(title=title, genre=genre)
    db.session.add(work)
    db.session.flush()
    part.add_work(work)
    db.session.commit()
    return jsonify({"status": "ok", "work": {"id": work.id, "title": work.title, "genre": work.genre}})


@bp_document.route("/api/parts/<int:part_id>/works/<int:work_id>", methods=["DELETE"])
@requires_access(Part, 'part_id')
def api_part_remove_work(part: Part, work_id):
    part.remove_work(work_id)
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Update document status
# -------------------------

@bp_document.route("/api/documents/<int:document_id>/status", methods=["POST"])
@requires_access(Document, 'document_id')
def api_document_status(document: Document):
    document.status = request.json.get("status", document.status)
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Background normalization progress (polled by the editor while a document
# is "in process" — replaces the old held-open SSE connection from
# /api/normalize)
# -------------------------

def _job_progress_dict(job: NormalizationJob | None) -> dict:
    if job is None or job.status == "done":
        return {"processing": False, "status": job.status if job else None,
                "current": 0, "total": 0, "error": None}
    return {
        "processing": job.status in ("queued", "running"),
        "status": job.status,
        "current": job.processed_chunks,
        "total": job.total_chunks,
        "error": job.error,
    }


@bp_document.route("/api/documents/<int:document_id>/processing-status")
@requires_access(Document, 'document_id')
def api_document_processing_status(document: Document):
    return jsonify(_job_progress_dict(document.active_job))


@bp_document.route("/api/documents/<int:document_id>/annotations")
@requires_access(Document, 'document_id')
def api_document_annotations(document: Document):
    """Lets the editor re-fetch the current annotation set while a
    NormalizationJob is running, so already-processed chunks render as
    normalized text/highlights without a full page reload."""
    return jsonify({
        "annotations": document.annotations or [],
        **_job_progress_dict(document.active_job),
    })


# -------------------------
# Reprocess: re-run normalization on a document's current lines, discarding
# its existing annotations. Lets you re-check normalization/alignment on a
# document that's already been imported, the same way "delete" lets you
# discard one — exposed from the metadata modal.
# -------------------------

@bp_document.route("/api/documents/<int:document_id>/reprocess", methods=["POST"])
@requires_access(Document, 'document_id')
def api_document_reprocess(document: Document):
    active = document.active_job
    if active is not None and active.status in ("queued", "running"):
        abort(409)

    # Normalise whitespace on existing lines in place: documents imported
    # before this normalisation existed may still carry multi-space/multi-
    # newline runs in original_text, which is exactly what caused the
    # alignment drift reprocessing is meant to fix (see normalize_whitespace's
    # docstring). Document.full_text is derived live from these rows, so
    # updating them here keeps it in lockstep with the chunks below.
    parts_lines = []
    for part in document.parts:
        part_lines = []
        for line in part.lines:
            line.original_text = normalize_whitespace(line.original_text)
            part_lines.append(line.original_text)
        parts_lines.append(part_lines)

    # Discard the previous run's annotations — reprocessing replaces them,
    # it doesn't layer a second set on top.
    document.set_annotations([])

    _queue_normalization_job(document, parts_lines, request.json or {})
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Update document metadata (label/qid/status)
# -------------------------

@bp_document.route("/documents/<int:document_id>/edit", methods=["POST"])
@requires_access(Document, 'document_id')
def document_update(document: Document):
    data = request.json if request.is_json else request.form
    if "label" in data:
        document.label = (data.get("label") or "").strip() or document.label
    if "status" in data:
        document.status = data.get("status", document.status)
    if "qid" in data:
        document.qid = data.get("qid") or None
    if "original_filename" in data and document.parts:
        # Editing original_filename through this form only makes sense for the
        # common single-part case; multi-part documents manage filenames per
        # part at import time.
        document.parts[0].original_filename = data.get("original_filename") or None
    db.session.commit()
    if request.is_json:
        return jsonify({"status": "ok"})
    flash("Document updated", "success")
    return redirect(request.form.get("next") or url_for("bp_document.document_editor", document_id=document.id))


# -------------------------
# Move document to another folder (extract)
# -------------------------

@bp_document.route("/documents/<int:document_id>/move", methods=["POST"])
@requires_access(Document, 'document_id')
def document_move(document: Document):
    data = request.json or {}
    new_folder_id = data.get("folder_id")
    if not new_folder_id:
        abort(400)
    new_folder_id = int(new_folder_id)
    new_folder = Folder.query.get_or_404(new_folder_id)
    if not new_folder.user_has_access(current_user):
        abort(403)
    if new_folder_id == document.folder_id:
        return jsonify({"status": "ok"})

    max_order = db.session.query(func.max(Document.order)).filter_by(folder_id=new_folder_id).scalar()
    document.folder_id = new_folder_id
    document.order = (max_order or 0) + 1
    db.session.commit()
    return jsonify({"status": "ok", "folder_id": new_folder_id})


# -------------------------
# Delete document
# -------------------------

@bp_document.route("/documents/<int:document_id>/delete")
@requires_access(Document, 'document_id')
def document_delete(document: Document):
    if request.args.get("confirm", type=bool, default=False):
        folder_id = document.folder_id
        db.session.delete(document)
        db.session.commit()
        flash("Document deleted", "success")
        return redirect(url_for("bp_folder.folder_browse", folder_id=folder_id))
    return render_template("documents/delete.html", page=document)


# -------------------------
# TEI export of a single document
# -------------------------

@bp_document.route("/documents/<int:document_id>/stats")
@requires_access(Document, 'document_id')
def document_stats(document: Document):
    from .stats_report import compute_stats, build_chart_svg, load_font_face, today_str
    stats = compute_stats([document])
    html = render_template('stats_report.html',
        title=document.label,
        stats=stats,
        chart_svg=build_chart_svg(stats),
        font_face=load_font_face(),
        generated=today_str(),
        scope='page',
    )
    return Response(html, mimetype='text/html',
                    headers={'Content-Disposition': f'attachment; filename="stats-{document.label}.html"'})


@bp_document.route("/documents/<int:document_id>/export")
@requires_access(Document, 'document_id')
def document_export_tei(document: Document):
    users_by_id = {u.id: u.nickname or u.username for u in User.query.all()}
    tei = build_tei_from_annotations(document.full_text, document.annotations or [], users_by_id=users_by_id,
                                      metadata=document_metadata(document), lines=document.line_offsets,
                                      subparts=document.part_offsets)
    return Response(
        tei,
        mimetype="text/xml",
        headers={"Content-Disposition": f'attachment; filename="{document.label}.xml"'}
    )


# -------------------------
# Document works CRUD
# -------------------------

@bp_document.route("/api/documents/<int:document_id>/works", methods=["POST"])
@requires_access(Document, 'document_id')
def api_document_add_work(document: Document):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400)
    genre = (data.get("genre") or "").strip() or None
    work = Work(title=title, genre=genre)
    db.session.add(work)
    db.session.flush()
    document.add_work(work)
    db.session.commit()
    return jsonify({"status": "ok", "work": {"id": work.id, "title": work.title, "genre": work.genre}})


@bp_document.route("/api/documents/<int:document_id>/works/<int:work_id>", methods=["DELETE"])
@requires_access(Document, 'document_id')
def api_document_remove_work(document: Document, work_id):
    document.remove_work(work_id)
    db.session.commit()
    return jsonify({"status": "ok"})
