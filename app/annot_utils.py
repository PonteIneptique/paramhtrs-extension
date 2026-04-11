from uuid import uuid4
from xml.sax.saxutils import escape


def _get_selector(annot: dict, selector_type: str) -> dict:
    for sel in annot.get("target", {}).get("selector", []):
        if sel.get("type") == selector_type:
            return sel
    return {}


def _make_annot(text: str, start: int, end: int, value: str, purpose: str) -> dict:
    annot_id = str(uuid4())
    return {
        "id": annot_id,
        "type": "Annotation",
        "body": [{"type": "TextualBody", "value": value, "purpose": purpose}],
        "target": {
            "annotation": annot_id,   # Recogito requires this back-reference
            "selector": [
                {"type": "TextPositionSelector", "start": start, "end": end},
                {
                    "type": "TextQuoteSelector",
                    "exact": text[start:end],
                    "prefix": text[max(0, start - 10):start],
                    "suffix": text[end:end + 10],
                },
            ],
        },
    }


def align_to_annotations(original_text: str, regularized_text: str) -> list:
    """Convert align_words() output to W3C Web Annotation JSON."""
    from .alignment import align_words
    alignments = align_words(original_text, regularized_text)
    annotations = []
    char_pos = 0
    for almt in alignments:
        src_len = len(almt.source)
        if almt.code == 'n' or (almt.code == 's' and almt.source == almt.target):
            char_pos += src_len
        elif almt.code == 's':
            # Skip substitutions that are whitespace-only on both sides
            if not almt.source.strip() and not almt.target.strip():
                char_pos += src_len
                continue
            start, end = char_pos, char_pos + src_len
            annotations.append(_make_annot(original_text, start, end, almt.target, "normalizing"))
            char_pos += src_len
        elif almt.code == 'd':
            # Skip deletion of whitespace-only spans
            if not almt.source.strip():
                char_pos += src_len
                continue
            start, end = char_pos, char_pos + src_len
            annotations.append(_make_annot(original_text, start, end, "", "deletion"))
            char_pos += src_len
        elif almt.code == 'i':
            # Skip insertion of whitespace-only content
            if not almt.target.strip():
                continue
            annotations.append(_make_annot(original_text, char_pos, char_pos, almt.target, "insertion"))
            # insertion does not consume source characters
    return annotations


def apply_annotations_to_text(original_text: str, annotations: list) -> str:
    """Produce normalized plaintext by applying annotations right-to-left."""
    if not annotations:
        return original_text
    sorted_annots = sorted(
        annotations,
        key=lambda a: _get_selector(a, "TextPositionSelector").get("start", 0),
        reverse=True,
    )
    result = original_text
    for annot in sorted_annots:
        pos = _get_selector(annot, "TextPositionSelector")
        start = pos.get("start", 0)
        end = pos.get("end", 0)
        body = annot.get("body", [{}])[0] if annot.get("body") else {}
        value = body.get("value", "")
        result = result[:start] + value + result[end:]
    return result


def _escape_segment(text: str) -> str:
    """Escape plain text segment, replacing newlines with <lb/>."""
    result = []
    for segment in text.split("\n"):
        if result:
            result.append("<lb/>")
        result.append(escape(segment))
    return "".join(result)


def build_tei_from_annotations(original_text: str, annotations: list) -> str:
    """Build TEI markup from page full_text + W3C annotations.

    Newlines in original_text become <lb/>. Each logical line is wrapped
    in <l>...</l> only when building per-page output; callers that want
    per-line <l> elements should split on '\\n' themselves.
    """
    sorted_annots = sorted(
        annotations,
        key=lambda a: _get_selector(a, "TextPositionSelector").get("start", 0),
    )
    parts = []
    cursor = 0
    for annot in sorted_annots:
        pos = _get_selector(annot, "TextPositionSelector")
        start = pos.get("start", 0)
        end = pos.get("end", 0)
        body = annot.get("body", [{}])[0] if annot.get("body") else {}
        purpose = body.get("purpose", "normalizing")
        value = body.get("value", "")
        if cursor < start:
            parts.append(_escape_segment(original_text[cursor:start]))
        orig_span = escape(original_text[start:end])
        if purpose == "normalizing":
            parts.append(
                f'<choice><orig>{orig_span}</orig><reg>{escape(value)}</reg></choice>'
            )
        elif purpose == "deletion":
            parts.append(f'<surplus>{orig_span}</surplus>')
        elif purpose == "insertion":
            parts.append(f'<supplied>{escape(value)}</supplied>')
        cursor = end
    if cursor < len(original_text):
        parts.append(_escape_segment(original_text[cursor:]))
    inner = "".join(parts)
    # Wrap each line segment in <l>...</l>
    lines_tei = []
    for line_part in inner.split("<lb/>"):
        lines_tei.append(f"<l>{line_part}</l>")
    return "\n<lb/>\n".join(lines_tei)
