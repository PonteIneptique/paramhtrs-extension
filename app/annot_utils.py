from uuid import uuid4
import re
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
    """
    Builds TEI with regularized text in <body> and original source text inside
    the <span> tags in <standOff>.
    """
    # 1. Sort annotations by start position
    sorted_annots = sorted(
        annotations,
        key=lambda a: _get_selector(a, "TextPositionSelector").get("start", 0)
    )

    body_parts = []
    span_entries = []

    word_count = 0
    cursor = 0
    tokens_on_line = 0

    def process_segment(text, orig_label=None, force_lb_at_end=False):
        """
        Tokenizes 'text' (regularized) and links tokens to 'orig_label'
        (the messy source) in the standoff.
        """
        nonlocal word_count, tokens_on_line
        local_ids = []

        # Split text into lines
        lines = text.split('\n')
        for i, line in enumerate(lines):
            # Tokenize words/punctuation
            line_tokens = list(re.finditer(r"(\w+)|([^\w\s]+)", line))

            for j, match in enumerate(line_tokens):
                word_count += 1
                tokens_on_line += 1
                w_id = f"w{word_count}"
                tag = "pc" if match.group(2) else "w"
                token_xml = f'<{tag} xml:id="{w_id}">{escape(match.group(0))}</{tag}>'

                body_parts.append(token_xml)
                local_ids.append(f"#{w_id}")

                # Logic for <lb/> based on line breaks or forced end-of-annot breaks
                is_last_of_line = (j == len(line_tokens) - 1)
                is_last_of_annot = (i == len(lines) - 1 and is_last_of_line)

                if (i < len(lines) - 1 and is_last_of_line) or (is_last_of_annot and force_lb_at_end):
                    body_parts.append('<lb break="no" precision="low"/>\n        ')
                    tokens_on_line = 0
                elif tokens_on_line >= 10:
                    body_parts.append("\n        ")
                    tokens_on_line = 0

            # Handle static text line breaks (empty lines)
            if not line.strip() and len(lines) > 1 and i < len(lines) - 1:
                body_parts.append('<lb/>\n        ')
                tokens_on_line = 0

        # Link IDs to the original source text directly in the span
        if orig_label is not None and local_ids:
            span_entries.append(
                f'      <span target="{" ".join(local_ids)}">{escape(orig_label)}</span>'
            )

    # 2. Linear processing of segments
    for annot in sorted_annots:
        pos = _get_selector(annot, "TextPositionSelector")
        start, end = pos.get("start", 0), pos.get("end", 0)

        # Static text
        if start > cursor:
            process_segment(original_text[cursor:start])

        # Annotation
        body = annot.get("body", [{}])[0]
        reg_value = body.get("value", "")
        orig_value = original_text[start:end]

        # Detect if we need the custom non-breaking LB
        has_lb_in_orig = '\n' in orig_value

        # Map regularized tokens to original string content
        process_segment(reg_value, orig_label=orig_value, force_lb_at_end=has_lb_in_orig)
        cursor = end

    # Trailing text
    if cursor < len(original_text):
        process_segment(original_text[cursor:])

    # 3. Final Assembly
    full_body = " ".join(body_parts).replace(" \n", "\n").replace("\n ", "\n")

    return f'''<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Standoff TEI Export</title></titleStmt>
      <publicationStmt><p>Cleaned Standoff Mapping</p></publicationStmt>
      <sourceDesc><p>Linear processing with direct span content</p></sourceDesc>
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