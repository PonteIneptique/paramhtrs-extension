from uuid import uuid4
import re
from xml.sax.saxutils import escape
import re
from xml.sax.saxutils import escape

# Use cdifflib for speed if available, fallback to standard difflib
try:
    from cdifflib import CSequenceMatcher as SequenceMatcher
except ImportError:
    from difflib import SequenceMatcher


def find_split_point(orig: str, reg: str) -> int:
    """
    Finds the index in the regularized word that logically
    corresponds to the '\n' in the original word.
    """
    # 1. Clean the original for a fair comparison
    orig_clean = orig.replace('\n', '')

    # 2. Align characters
    s = SequenceMatcher(None, orig_clean, reg)
    nl_pos = orig.find('\n')

    # 3. Find the best matching block for the character before the newline
    for block in s.get_matching_blocks():
        if block.a <= nl_pos <= block.a + block.size:
            # Calculate the relative offset in the regularized string
            return block.b + (nl_pos - block.a)

    return len(reg)

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


def _alignments_to_annotations(alignments: list, reference_text: str, char_offset: int = 0) -> list:
    """Convert Alignment objects to W3C annotations with positions relative to reference_text."""
    annotations = []
    pos = char_offset
    for almt in alignments:
        src_len = len(almt.source)
        if almt.code == 'n' or (almt.code == 's' and almt.source == almt.target):
            pos += src_len
        elif almt.code == 's':
            if not almt.source.strip() and not almt.target.strip():
                pos += src_len
                continue
            annotations.append(_make_annot(reference_text, pos, pos + src_len, almt.target, "normalizing"))
            pos += src_len
        elif almt.code == 'd':
            if not almt.source.strip():
                pos += src_len
                continue
            annotations.append(_make_annot(reference_text, pos, pos + src_len, "", "deletion"))
            pos += src_len
        elif almt.code == 'i':
            if not almt.target.strip():
                continue
            annotations.append(_make_annot(reference_text, pos, pos, almt.target, "insertion"))
    return annotations


def align_to_annotations(original_text: str, regularized_text: str) -> list:
    """Convert align_words() output to W3C Web Annotation JSON."""
    from .alignment import align_words
    alignments = align_words(original_text, regularized_text)
    return _alignments_to_annotations(alignments, original_text)


def align_to_annotations_from_chunks(chunks: list[dict], separator: str = "\n") -> list:
    """Align each (orig, reg) chunk pair independently and return consolidated annotations.

    Aligning per-chunk keeps each sub-problem small and scoped to what the
    normalisation model actually saw, so the edit-distance DP is more accurate
    than aligning the entire page at once.

    Args:
        chunks:    list of {"orig": str, "reg": str} dicts (in document order)
        separator: string that was placed between consecutive orig chunks when
                   the full page text was assembled.  Typically "\n" (lines
                   mode) or " " (dots mode).  Pilcrow chunks already carry
                   their own delimiter so separator="" is correct there.
    """
    from .alignment import align_words
    reference_text = separator.join(c["orig"] for c in chunks)
    all_annotations = []
    char_offset = 0
    for idx, chunk in enumerate(chunks):
        orig, reg = chunk["orig"], chunk.get("reg", "")
        if reg:
            alignments = align_words(orig, reg)
            all_annotations.extend(_alignments_to_annotations(alignments, reference_text, char_offset))
        char_offset += len(orig)
        if idx < len(chunks) - 1:
            char_offset += len(separator)
    return all_annotations


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
    sorted_annots = sorted(
        annotations,
        key=lambda a: _get_selector(a, "TextPositionSelector").get("start", 0)
    )

    body_parts = []
    span_entries = []
    word_count, cursor, tokens_on_line = 0, 0, 0

    def process_segment(text, orig_label=None):
        nonlocal word_count, tokens_on_line
        local_ids = []
        has_internal_lb = orig_label and '\n' in orig_label

        # Tokenize reg value (words, punctuation, or manual newlines)
        tokens = list(re.finditer(r"(\w+)|([^\w\s]+)|(\n)", text))

        for match in tokens:
            val = match.group(0)
            if match.group(3):  # \n in regularization
                body_parts.append('<lb/>\n        ')
                tokens_on_line = 0
                continue

            word_count += 1
            tokens_on_line += 1
            w_id = f"w{word_count}"
            tag = "pc" if match.group(2) else "w"
            local_ids.append(f"#{w_id}")

            if has_internal_lb:
                # Surgical split
                split_idx = find_split_point(orig_label, val)
                part1, part2 = val[:split_idx], val[split_idx:]
                lb_tag = '<lb break="no" precision="low"/>'
                token_xml = f'<{tag} xml:id="{w_id}">{escape(part1)}{lb_tag}{escape(part2)}</{tag}>'
                tokens_on_line = 0  # Force wrap after an internal lb
            else:
                token_xml = f'<{tag} xml:id="{w_id}">{escape(val)}</{tag}>'

            body_parts.append(token_xml)

            # Beautification wrapping
            if tokens_on_line >= 10:
                body_parts.append("\n        ")
                tokens_on_line = 0

        if orig_label and local_ids:
            span_entries.append(f'      <span target="{" ".join(local_ids)}">{escape(orig_label)}</span>')

    # Main Loop
    for annot in sorted_annots:
        pos = _get_selector(annot, "TextPositionSelector")
        start, end = pos.get("start", 0), pos.get("end", 0)

        if start > cursor:
            process_segment(original_text[cursor:start])

        body = annot.get("body", [{}])[0]
        process_segment(body.get("value", ""), orig_label=original_text[start:end])
        cursor = end

    if cursor < len(original_text):
        process_segment(original_text[cursor:])

    # Cleanup formatting
    full_body = " ".join(body_parts).replace(" \n", "\n").replace("\n ", "\n")

    return f'''<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Standoff Export</title></titleStmt>
      <publicationStmt><p>Fast Standoff via cdifflib</p></publicationStmt>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <p>
        {full_body.strip()}
      </p>
    </body>
  </text>
  <standOff>
    <spanGrp type="wordForm">
{chr(10).join(span_entries)}
    </spanGrp>
  </standOff>
</TEI>'''