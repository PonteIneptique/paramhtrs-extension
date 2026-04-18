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

    max_chunk_bytes = int(data.get("max_chunk_bytes", 512))
    delimiters = list(data.get("delimiters", "¶;."))

    if split_mode == "lines":
        # One model call per line; full_reg is newline-joined normalized lines.
        raw_chunks = _enforce_max_bytes(orig_lines, max_chunk_bytes)
        separator = "\n"

        def generate():
            total = len(raw_chunks)
            pairs = []
            for i, chunk in enumerate(raw_chunks):
                reg = normalize_line(chunk, model, tokenizer)
                pairs.append({"orig": chunk, "reg": reg})
                yield _sse_event("progress", {"current": i + 1, "total": total,
                                              "result": {"orig": chunk, "reg": reg}})
            yield _sse_event("done", {
                "full_reg": separator.join(p["reg"] for p in pairs),
                "chunks": pairs,
                "separator": separator,
            })

    else:
        if split_mode == "punctuation":
            full_text = " ".join(orig_lines)
            batch_chunks = _split_on_punct(full_text, delimiters, min_words)
            separator = " "
        else:
            batch_chunks = orig_lines
            separator = "\n"

        batch_chunks = _enforce_max_bytes(batch_chunks, max_chunk_bytes)

        # One model call per batch; full_reg is joined normalized chunks.
        def generate():
            total = len(batch_chunks)
            pairs = []
            for i, chunk in enumerate(batch_chunks):
                reg = normalize_line(chunk, model, tokenizer)
                pairs.append({"orig": chunk, "reg": reg})
                yield _sse_event("progress", {"current": i + 1, "total": total,
                                              "result": {"orig": chunk, "reg": reg}})
            yield _sse_event("done", {
                "full_reg": separator.join(p["reg"] for p in pairs),
                "chunks": pairs,
                "separator": separator,
            })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse_event(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _sse_done(full_reg: str) -> str:
    yield _sse_event("done", {"full_reg": full_reg})


def _split_on_punct(text: str, delimiters: list[str], min_words: int) -> list[str]:
    """Split text after any delimiter character, accumulating until min_words is reached."""
    escaped = [re.escape(d) for d in delimiters]
    pattern = r"(?<=[" + "".join(escaped) + r"])\s+"
    sentences = [s for s in re.split(pattern, text) if s.strip()]
    chunks = []
    current: list[str] = []
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


def _enforce_max_bytes(chunks: list[str], max_bytes: int) -> list[str]:
    """Sub-split any chunk exceeding max_bytes at the nearest preceding space."""
    result = []
    for chunk in chunks:
        while len(chunk.encode()) > max_bytes:
            # Find split point within max_bytes
            encoded = chunk.encode()
            split_pos = encoded[:max_bytes].rfind(b" ")
            if split_pos <= 0:
                split_pos = max_bytes
            head = encoded[:split_pos].decode(errors="ignore")
            tail = encoded[split_pos:].decode(errors="ignore").lstrip()
            result.append(head)
            chunk = tail
        result.append(chunk)
    return [c for c in result if c.strip()]


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
