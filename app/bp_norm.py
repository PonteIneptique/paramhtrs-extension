import os
import json
import re

from flask import Blueprint, render_template, request, jsonify, abort, Response, stream_with_context
from flask_login import login_required, current_user

from .models import db, Line, Page
from .bp_auth import requires_access

bp_norm = Blueprint(
    "bp_norm", __name__,
    template_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "template"),
    static_folder=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "static"),
    static_url_path=''
)


# -------------------------
# Ingestion wizard entry point
# -------------------------

@bp_norm.route("/ingestion/new")
@login_required
def ingestion_new():
    from .models import Document
    project_id = request.args.get("project_id", type=int)
    document_id = request.args.get("document_id", type=int)
    document = None
    if document_id:
        document = Document.query.get_or_404(document_id)
        if not document.user_has_access(current_user):
            abort(403)
    return render_template("ingestion/create.html",
                           project_id=project_id,
                           document_id=document_id,
                           document=document)


# -------------------------
# Normalize text via model (called from wizard)
#
# Streams SSE progress events, then a final "done" event with `full_reg`:
# the complete normalized text of the page (all batches joined).  The caller
# passes `full_reg` verbatim to POST /pages/new — no per-line realignment needed.
# -------------------------

@bp_norm.route("/api/normalize", methods=["POST"])
@login_required
def api_normalize():
    from .process import normalize_line, get_model_and_tokenizer
    model, tokenizer = get_model_and_tokenizer()
    data = request.json
    split_mode = data.get("split_mode", "lines")
    min_words = int(data.get("min_words", 100))
    raw_text = data.get("inputtext", "")

    orig_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not orig_lines:
        return Response(_sse_done(""), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if split_mode == "lines":
        # One model call per line; full_reg is newline-joined normalized lines.
        def generate():
            total = len(orig_lines)
            normalized = []
            for i, line in enumerate(orig_lines):
                reg = normalize_line(line, model, tokenizer)
                normalized.append(reg)
                yield _sse_event("progress", {"current": i + 1, "total": total,
                                              "result": {"orig": line, "reg": reg}})
            yield _sse_event("done", {"full_reg": "\n".join(normalized)})

    else:
        if split_mode == "pilcrow":
            # Split after each ¶ (lookbehind keeps the ¶ in its chunk)
            full_text = "\n".join(orig_lines)
            chunks = [c for c in re.split(r"(?<=¶)", full_text) if c.strip()]
        elif split_mode == "dots":
            full_text = " ".join(orig_lines)
            chunks = _split_on_dots(full_text, min_words)
        else:
            chunks = orig_lines

        # One model call per batch; full_reg is space-joined normalized chunks.
        def generate():
            total = len(chunks)
            normalized = []
            for i, chunk in enumerate(chunks):
                reg = normalize_line(chunk, model, tokenizer)
                normalized.append(reg)
                yield _sse_event("progress", {"current": i + 1, "total": total,
                                              "result": {"orig": chunk, "reg": reg}})
            yield _sse_event("done", {"full_reg": " ".join(normalized)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_event(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _sse_done(full_reg: str) -> str:
    yield _sse_event("done", {"full_reg": full_reg})


def _split_on_dots(text: str, min_words: int) -> list[str]:
    """Split text on sentence-ending dots, ensuring each chunk has at least min_words.
    The dot is kept at the end of its chunk via lookbehind."""
    sentences = re.split(r"(?<=\w\.)\s+", text)
    chunks = []
    current = []
    word_count = 0
    for sent in sentences:
        current.append(sent)
        word_count += len(sent.split())
        if word_count >= min_words:
            chunks.append(" ".join(current))
            current = []
            word_count = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


# -------------------------
# Save annotations on a page (auto-save, replaces all annotations)
# -------------------------

@bp_norm.route("/api/pages/<int:page_id>/annotations", methods=["PUT"])
@requires_access(Page, 'page_id')
def api_page_save_annotations(page: Page):
    data = request.json
    page.annotations = data.get("annotations", [])
    db.session.commit()
    return jsonify({"status": "ok", "normalized_text": page.normalized_text})


# -------------------------
# Delete a line
# -------------------------

@bp_norm.route("/api/lines/<int:line_id>/delete", methods=["GET", "POST", "DELETE"])
@requires_access(Line, 'line_id')
def line_delete(line: Line):
    page_id = line.page_id
    db.session.delete(line)
    db.session.commit()
    return jsonify({"status": "ok", "page_id": page_id})
