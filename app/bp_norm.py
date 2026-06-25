import os
import json
import re

from flask import Blueprint, render_template, request, jsonify, abort, Response, stream_with_context
from flask_login import login_required, current_user

from .models import db, Line, Document, Annotation
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
    from .models import Folder
    project_id = request.args.get("project_id", type=int)
    folder_id = request.args.get("folder_id", type=int)
    folder = None
    if folder_id:
        folder = Folder.query.get_or_404(folder_id)
        if not folder.user_has_access(current_user):
            abort(403)
    return render_template("ingestion/create.html",
                           project_id=project_id,
                           folder_id=folder_id,
                           folder=folder)


# -------------------------
# Normalize text via model (called from wizard)
#
# Streams SSE progress events, then a final "done" event with `full_reg`:
# the complete normalized text of the document (all batches joined).  The
# caller passes `full_reg` verbatim to POST /documents/new — no per-line
# realignment needed.
# -------------------------

@bp_norm.route("/api/normalize", methods=["POST"])
@login_required
def api_normalize():
    from .process import normalize_line, get_model_and_tokenizer
    model, tokenizer = get_model_and_tokenizer()
    data = request.json
    split_mode = data.get("split_mode", "lines")
    min_words = int(data.get("min_words", 100))

    from flask import current_app
    max_chunk_bytes = current_app.config['MAX_CHUNK_BYTES']
    delimiters = list(data.get("delimiters", "¶;."))

    # `parts` (list of line-arrays, one per source file/part) keeps chunking
    # scoped within each part so punctuation-mode batches never merge lines
    # from different parts. Falls back to a single implicit part built from
    # `inputtext` for single-source callers.
    raw_parts = data.get("parts")
    if raw_parts is None:
        raw_text = data.get("inputtext", "")
        raw_parts = [raw_text.splitlines()]

    parts_lines = [[l.strip() for l in part if l.strip()] for part in raw_parts]
    if not any(parts_lines):
        return Response(_sse_done(""), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Build the list of (part_index, chunk) batches, splitting independently
    # within each part so chunk boundaries never cross a part boundary.
    batches = []
    for part_index, orig_lines in enumerate(parts_lines):
        if not orig_lines:
            continue
        if split_mode == "lines":
            part_chunks = orig_lines
            separator = "\n"
        elif split_mode == "punctuation":
            part_chunks = _split_on_punct(" ".join(orig_lines), delimiters, min_words)
            separator = " "
        else:
            part_chunks = orig_lines
            separator = "\n"
        part_chunks = _enforce_max_bytes(part_chunks, max_chunk_bytes)
        for chunk in part_chunks:
            batches.append({"part_index": part_index, "chunk": chunk, "separator": separator})

    def generate():
        total = len(batches)
        pairs = []
        for i, batch in enumerate(batches):
            reg = normalize_line(batch["chunk"], model, tokenizer)
            pair = {"orig": batch["chunk"], "reg": reg, "part_index": batch["part_index"]}
            pairs.append(pair)
            yield _sse_event("progress", {"current": i + 1, "total": total, "result": pair})

        full_reg_by_part = {}
        for pair in pairs:
            full_reg_by_part.setdefault(pair["part_index"], []).append(pair)
        separators_by_part = {b["part_index"]: b["separator"] for b in batches}
        parts_out = []
        for part_index in range(len(parts_lines)):
            part_pairs = full_reg_by_part.get(part_index, [])
            sep = separators_by_part.get(part_index, "\n")
            parts_out.append({
                "chunks": part_pairs,
                "full_reg": sep.join(p["reg"] for p in part_pairs),
                "separator": sep,
            })

        yield _sse_event("done", {
            "full_reg": "\n".join(p["full_reg"] for p in parts_out),
            "chunks": pairs,
            "parts": parts_out,
            "separator": parts_out[0]["separator"] if parts_out else "\n",
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
# Single-annotation upsert (hot path: validate, edit, create)
# -------------------------

@bp_norm.route("/api/documents/<int:document_id>/annotations/<annotation_id>", methods=["PUT"])
@requires_access(Document, 'document_id')
def api_page_save_annotation(document: Document, annotation_id: str):
    data = request.json
    if not data or data.get("id") != annotation_id:
        abort(400)
    Annotation.upsert_from_dict(document.id, data)
    db.session.commit()
    return jsonify({"status": "ok"})


@bp_norm.route("/api/documents/<int:document_id>/annotations/<annotation_id>", methods=["DELETE"])
@requires_access(Document, 'document_id')
def api_page_delete_annotation(document: Document, annotation_id: str):
    Annotation.query.filter_by(id=annotation_id, document_id=document.id).delete()
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Bulk replace — kept for structural operations (line deletion, clear pending)
# -------------------------

@bp_norm.route("/api/documents/<int:document_id>/annotations", methods=["PUT"])
@requires_access(Document, 'document_id')
def api_page_save_annotations(document: Document):
    data = request.json
    document.set_annotations(data.get("annotations", []))
    db.session.commit()
    return jsonify({"status": "ok"})


# -------------------------
# Delete a line
# -------------------------

@bp_norm.route("/api/lines/<int:line_id>/delete", methods=["GET", "POST", "DELETE"])
@requires_access(Line, 'line_id')
def line_delete(line: Line):
    document_id = line.part.document_id
    db.session.delete(line)
    db.session.commit()
    return jsonify({"status": "ok", "document_id": document_id})
