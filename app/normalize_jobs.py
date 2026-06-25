"""Chunking logic shared between the (legacy) SSE /api/normalize route and the
queued NormalizationJob path (app/bp_document.py, worker.py). Splitting is pure
and cheap (no model call) so it can run synchronously at document-creation time,
fixing every chunk's position before the model ever sees the text -- that's what
lets the worker persist annotations for one chunk as soon as it's normalized,
independently of the chunks around it.
"""
import re


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
