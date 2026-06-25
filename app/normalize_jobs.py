"""Chunking logic shared between the (legacy) SSE /api/normalize route and the
queued NormalizationJob path (app/bp_document.py, worker.py). Splitting is pure
and cheap (no model call) so it can run synchronously at document-creation time,
fixing every chunk's position before the model ever sees the text -- that's what
lets the worker persist annotations for one chunk as soon as it's normalized,
independently of the chunks around it.
"""
import re

_RE_NEWLINE_RUN = re.compile(r"[ \t]*\n[ \t\n]*")
_RE_SPACE_RUN = re.compile(r"[ \t]+")


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs so every chunk's length stays in lockstep with
    the offset bookkeeping done around it (build_chunks/worker.py/
    align_to_annotations_from_chunks all advance char_offset by len(orig)).

    char_alignment.align_words() normalises whitespace internally (RE_SPACE)
    before running its DP, which silently shortens any run of 2+ whitespace
    characters. If the text fed in still had such runs, the alignment's
    source spans no longer sum to len(orig), and every annotation positioned
    after that point in the chunk drifts off its real character offset --
    compounding into the kind of document-wide misalignment seen on
    long/multi-line documents with irregular OCR spacing. Normalising here,
    before the text ever reaches build_chunks or get stored as a Line, keeps
    that internal collapse a no-op.

    A whitespace run containing a newline collapses to a single '\\n'; any
    other run of spaces/tabs collapses to a single ' '.
    """
    text = _RE_NEWLINE_RUN.sub("\n", text)
    text = _RE_SPACE_RUN.sub(" ", text)
    return text


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


def build_chunks(parts_lines: list[list[str]], split_mode: str, min_words: int,
                  delimiters: list[str], max_chunk_bytes: int) -> tuple[list[dict], str]:
    """Split each part's lines independently into model-input chunks, never
    merging lines across a part boundary (so e.g. punctuation-mode batches stay
    scoped to one ALTO file/part even when a Document has several).

    Returns (chunks, separator):
      chunks:    ordered list of {"part_index": int, "orig": str}
      separator: the single string placed between every consecutive chunk
                 job-wide (also used to join lines within a part before
                 punctuation-splitting) -- "\n" for lines mode, " " for
                 punctuation mode. A single separator value can be reused
                 uniformly across part boundaries because Document.full_text
                 already joins every line, across every part, with "\n"
                 (app/models.py: Document.full_text) -- part boundaries are
                 not special-cased there, so neither are they here.
    """
    separator = " " if split_mode == "punctuation" else "\n"
    chunks = []
    for part_index, orig_lines in enumerate(parts_lines):
        if not orig_lines:
            continue
        if split_mode == "punctuation":
            part_chunks = _split_on_punct(" ".join(orig_lines), delimiters, min_words)
        else:
            part_chunks = orig_lines
        part_chunks = _enforce_max_bytes(part_chunks, max_chunk_bytes)
        for chunk in part_chunks:
            chunks.append({"part_index": part_index, "orig": chunk})
    return chunks, separator
