"""Part-aware chunking for the queued NormalizationJob path (app/bp_document.py,
worker.py).

The chunking algorithm itself now lives in penelopy (penelopy.chunking.chunker,
extracted from this module). What stays here is the Document/Part-aware wrapper:
splitting is pure and cheap (no model call) so it runs synchronously at
document-creation time, fixing every chunk's position before the model ever sees
the text -- that's what lets the worker persist annotations for one chunk as soon
as it's normalized, independently of the chunks around it.

This calls penelopy's `_split_on_punct`/`_enforce_max_bytes` rather than its
public `build_chunks`, which takes a whole document as one string: a Line's
`original_text` can itself contain a newline (rare, but present in real data),
and round-tripping through a "\n"-joined string would silently re-split such a
Line into several chunks and hand the model different input than it gets today.
Feeding the per-part line list straight to the two primitives keeps chunking
byte-for-byte identical to the pre-penelopy behaviour.
"""
from penelopy.chunking.chunker import (
    _enforce_max_bytes,
    _split_on_punct,
    normalize_whitespace,
)

__all__ = ["normalize_whitespace", "build_chunks"]


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
            part_chunks = _split_on_punct(" ".join(orig_lines), tuple(delimiters), min_words)
        else:
            part_chunks = orig_lines
        part_chunks = _enforce_max_bytes(part_chunks, max_chunk_bytes)
        for chunk in part_chunks:
            chunks.append({"part_index": part_index, "orig": chunk})
    return chunks, separator
