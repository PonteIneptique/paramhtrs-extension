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

SEMTAG_TAGS = {
    "persName":  "persName",
    "orgName":   "orgName",
    "placeName": "placeName",
    "num":       "num",
}


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
    for idx, almt in enumerate(alignments):
        src_len = len(almt.source)
        if almt.code == 'n' or (almt.code == 's' and almt.source == almt.target):
            pos += src_len
        elif almt.code == 's':
            if not almt.source.strip() and not almt.target.strip():
                pos += src_len
                continue
            # Extend the annotation span by one character when the target value
            # already ends with the character immediately following the source span.
            # Without this, reconstruction appends that character twice: once from
            # the annotation value and once from the original text gap.
            # Only safe when the next alignment is a plain match (or there is
            # none): if it's its own substitution/deletion/insertion, that
            # character already gets its own annotation and stealing it here
            # would create two overlapping annotations over the same span
            # (e.g. "gał."→"Gal.:" then "."→":" — the trailing "." must not
            # also be absorbed into the "gał"→"Gal." annotation).
            next_almt = alignments[idx + 1] if idx + 1 < len(alignments) else None
            end = pos + src_len
            if (almt.target
                    and (next_almt is None or next_almt.code == 'n')
                    and end < len(reference_text)
                    and reference_text[end] == almt.target[-1]):
                end += 1
            annotations.append(_make_annot(reference_text, pos, end, almt.target, "normalizing"))
            pos += src_len
        elif almt.code == 'd':
            if not almt.source.strip():
                pos += src_len
                continue
            annotations.append(_make_annot(reference_text, pos, pos + src_len, "", "deletion"))
            pos += src_len
        elif almt.code == 'i':
            annotations.append(_make_annot(reference_text, pos, pos, almt.target, "insertion"))
    return annotations


def align_to_annotations(original_text: str, regularized_text: str) -> list:
    """Convert align_words() output to W3C Web Annotation JSON."""
    from .char_alignment import align_words
    alignments = align_words(original_text, regularized_text)
    return _alignments_to_annotations(alignments, original_text)


def align_one_chunk(orig: str, reg: str, full_text: str, char_offset: int) -> list:
    """Align a single (orig, reg) chunk pair and return annotations positioned
    against `full_text` starting at `char_offset`.

    `full_text` must be the real underlying document text (e.g.
    Document.full_text), NOT a separator-joined reconstruction of the chunks
    fed to the model. In punctuation/dots mode, a chunk's `orig` can span
    several original lines joined with a plain space — but the document's
    real text has a newline there. Both are 1 character, so char_offset math
    (purely additive over len(orig)/len(separator)) still lands on the right
    *position* either way, but if an edit happens to fall exactly on that
    joint, slicing a synthetic separator-joined string for the annotation's
    exact/prefix/suffix would grab the wrong character at that one spot.
    Slicing the real full_text instead is correct regardless.

    Factored out of align_to_annotations_from_chunks so the background
    normalization worker (worker.py) can call it one chunk at a time, as each
    chunk's `reg` comes back from the model, and persist that chunk's
    annotations immediately — without waiting for the rest of the document.
    """
    if not reg:
        return []
    from .char_alignment import align_words
    alignments = align_words(orig, reg)
    return _alignments_to_annotations(alignments, full_text, char_offset)


def align_to_annotations_from_chunks(chunks: list[dict], separator: str = "\n", full_text: str | None = None) -> list:
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
        full_text: the real underlying document text to slice annotation
                   context from (see align_one_chunk's docstring for why this
                   must NOT be the separator-joined chunk text in general).
                   Defaults to the separator-joined reconstruction for
                   backward compatibility when no real text is available,
                   but callers that have one (document_create, worker.py)
                   should always pass it.
    """
    if full_text is None:
        full_text = separator.join(c["orig"] for c in chunks)
    all_annotations = []
    char_offset = 0
    for idx, chunk in enumerate(chunks):
        orig, reg = chunk["orig"], chunk.get("reg", "")
        all_annotations.extend(align_one_chunk(orig, reg, full_text, char_offset))
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




def document_metadata(document) -> dict:
    """Extract TEI metadata dict from a Document ORM object."""
    folder = document.folder
    all_works = list(document.works) + list(folder.works)
    seen, unique_works = set(), []
    for w in all_works:
        if w.id not in seen:
            seen.add(w.id)
            unique_works.append({"title": w.title, "genre": w.genre})

    parts_meta = []
    for part in document.parts:
        if not (part.qid or part.works):
            continue
        parts_meta.append({
            "xml_id": f"part-{part.id}",
            "qid": part.qid,
            "works": [{"title": w.title, "genre": w.genre} for w in part.works],
        })

    return {
        "title": document.label,
        "document": folder.name,
        "project": folder.project.name,
        "language": folder.language,
        "qid": folder.qid,
        "document_qid": document.qid,
        "iiif_manifest_url": folder.iiif_manifest_url,
        "works": unique_works,
        "parts": parts_meta,
    }


def _ms_items_xml(works: list, indent: str) -> str:
    items = []
    for w in works:
        genre_attr = f' n="{escape(w["genre"])}"' if w.get("genre") else ""
        items.append(f'{indent}<msItem{genre_attr}><title>{escape(w["title"])}</title></msItem>')
    return ("\n" + "\n".join(items)) if items else ""


def build_tei_header(meta: dict, users_by_id: dict = None, contributor_ids: set = None) -> str:
    """Build a standalone <teiHeader> block from a metadata dict.

    metadata dict (all keys optional):
        title, document, project, language, qid, document_qid, iiif_manifest_url,
        works: list[{"title": str, "genre": str|None}]
        parts: list[{"xml_id": str, "qid": str|None, "works": list[{"title","genre"}]}]
            — per-Part metadata (only entries with a qid or works), rendered as
            <msPart> elements with @corresp pointing at the <milestone
            xml:id="..."/> marker emitted for the same part in the body (the
            msPart itself gets its own xml:id, distinct from the milestone's,
            since XML ids must be unique document-wide).
    """
    meta = meta or {}

    # titleStmt
    title_parts = [meta.get("document", ""), meta.get("title", "")]
    title_str = escape(" — ".join(p for p in title_parts if p) or "Standoff Export")

    # respStmt entries
    resp_stmts = ""
    if users_by_id and contributor_ids:
        stmts = []
        for uid in sorted(contributor_ids):
            name = users_by_id.get(uid)
            if name:
                stmts.append(f'        <respStmt><resp>annotator</resp><persName xml:id="{escape(name)}">{escape(name)}</persName></respStmt>')
        resp_stmts = "\n" + "\n".join(stmts) if stmts else ""

    # sourceDesc / msDesc
    source_desc_parts = []
    if meta.get("qid"):
        source_desc_parts.append(f'        <idno type="URI">{escape(meta["qid"])}</idno>')
    if meta.get("document_qid"):
        source_desc_parts.append(f'        <idno type="URI" subtype="document">{escape(meta["document_qid"])}</idno>')
    if meta.get("iiif_manifest_url"):
        source_desc_parts.append(f'        <idno type="IIIF">{escape(meta["iiif_manifest_url"])}</idno>')
    ms_contents = ""
    works = meta.get("works") or []
    if works:
        ms_contents = "\n        <msContents>" + _ms_items_xml(works, "          ") + "\n        </msContents>"

    ms_parts_xml = ""
    for part in meta.get("parts") or []:
        part_ident = ""
        if part.get("qid"):
            part_ident = f'\n          <msIdentifier>\n            <idno type="URI">{escape(part["qid"])}</idno>\n          </msIdentifier>'
        part_contents = ""
        if part.get("works"):
            part_contents = "\n          <msContents>" + _ms_items_xml(part["works"], "            ") + "\n          </msContents>"
        ms_parts_xml += (
            f'\n        <msPart xml:id="ms-{escape(part["xml_id"])}" corresp="#{escape(part["xml_id"])}">'
            f'{part_ident}{part_contents}\n        </msPart>'
        )

    if source_desc_parts or ms_contents or ms_parts_xml:
        ms_ident = ""
        if source_desc_parts:
            ms_ident = "\n        <msIdentifier>\n" + "\n".join(source_desc_parts) + "\n        </msIdentifier>"
        source_desc = f'''    <sourceDesc>
      <msDesc>{ms_ident}{ms_contents}{ms_parts_xml}
      </msDesc>
    </sourceDesc>'''
    else:
        source_desc = "    <sourceDesc><p>Exported from Abbreviarium</p></sourceDesc>"

    # profileDesc
    lang = escape(meta.get("language", ""))
    profile_desc = f'''    <profileDesc>
      <langUsage><language ident="{lang}"/></langUsage>
    </profileDesc>''' if lang else ""

    profile_block = f"\n  {profile_desc}" if profile_desc else ""

    return f'''  <teiHeader>
    <fileDesc>
      <titleStmt><title>{title_str}</title>{resp_stmts}
      </titleStmt>
      <publicationStmt><p>Exported from Abbreviarium</p></publicationStmt>
{source_desc}
    </fileDesc>{profile_block}
  </teiHeader>'''


def build_tei_from_annotations(original_text: str, annotations: list, users_by_id: dict = None, metadata: dict = None, lines: list = None, subparts: list = None) -> str:
    """Build a TEI XML document from annotations.

    metadata dict (all keys optional):
        title, document, project, language, qid,
        works: list[{"title": str, "genre": str|None}]

    lines: optional list of {"start": int, "alto_id": str|None} giving each
        original line's start offset within original_text (see Document.line_offsets).
        When provided, each <lb/> is annotated with @n=<alto_id> of the line it starts.

    subparts: optional list of {"start": int, "original_filename": str|None} giving
        each part's start offset within original_text (see Document.part_offsets).
        When a Document has more than one part, a <milestone unit="part"
        n="<original_filename>"/> is emitted at each boundary after the first.
    """
    sorted_annots = sorted(
        annotations,
        key=lambda a: _get_selector(a, "TextPositionSelector").get("start", 0)
    )

    line_alto_by_start = {l["start"]: l["alto_id"] for l in (lines or []) if l.get("alto_id")}
    subpart_milestones_by_start = {
        s["start"]: {
            "xml_id": f'part-{s.get("part_id", "")}',
            "n": s.get("original_filename") or str(s.get("part_id", "")),
        }
        for s in (subparts or [])[1:]
    }

    def _milestone_tag(m: dict) -> str:
        return f'<milestone unit="part" xml:id="{escape(m["xml_id"])}" n="{escape(m["n"])}"/>'

    body_parts = []
    span_entries = []
    word_count, cursor, tokens_on_line = 0, 0, 0
    annot_resp_id = None  # set per-annotation before calling process_segment

    if subparts and len(subparts) > 1:
        first = subparts[0]
        body_parts.append(_milestone_tag({
            "xml_id": f'part-{first.get("part_id", "")}',
            "n": first.get("original_filename") or str(first.get("part_id", "")),
        }) + '\n        ')

    if lines and lines[0].get("alto_id"):
        body_parts.append(f'<lb n="{escape(lines[0]["alto_id"])}"/>\n        ')

    def process_segment(text, orig_label=None, span_type=None, span_subtype=None, abs_start=0,
                         gap_before=False, gap_after=False):
        nonlocal word_count, tokens_on_line, annot_resp_id
        local_ids = []
        has_internal_lb = orig_label and '\n' in orig_label

        # A subpart boundary that falls *inside* an annotated span (the
        # annotation's original text crosses it) isn't caught by the \n-token
        # branch below, since the tokenized `text` here is often the
        # regularized value rather than the raw original text. Emit it once,
        # up front, so it isn't silently dropped — same fix as the UI divider.
        if has_internal_lb:
            for s in sorted(subpart_milestones_by_start):
                if abs_start < s < abs_start + len(orig_label):
                    body_parts.append(_milestone_tag(subpart_milestones_by_start[s]) + '\n        ')

        # Tokenize reg value (words, punctuation, or manual newlines)
        tokens = list(re.finditer(r"(\w+)|([^\w\s]+)|(\n)", text))
        content_indices = [i for i, m in enumerate(tokens) if not m.group(3)]
        first_idx = content_indices[0] if content_indices else None
        last_idx = content_indices[-1] if content_indices else None

        prev_end = 0
        for i, match in enumerate(tokens):
            # Preserve whitespace between tokens (spaces in source/value)
            if match.start() > prev_end:
                body_parts.append(escape(text[prev_end:match.start()]))
            prev_end = match.end()

            val = match.group(0)
            if match.group(3):  # \n in regularization
                next_line_start = abs_start + match.end()
                alto_id = line_alto_by_start.get(next_line_start)
                n_attr = f' n="{escape(alto_id)}"' if alto_id else ''
                subpart_m = subpart_milestones_by_start.get(next_line_start)
                if subpart_m is not None:
                    body_parts.append(_milestone_tag(subpart_m) + '\n        ')
                body_parts.append(f'<lb{n_attr}/>\n        ')
                tokens_on_line = 0
                continue

            word_count += 1
            tokens_on_line += 1
            w_id = f"w{word_count}"
            tag = "pc" if match.group(2) else "w"
            local_ids.append(f"#{w_id}")

            gap_open = "<gap/>" if gap_before and i == first_idx else ""
            gap_close = "<gap/>" if gap_after and i == last_idx else ""

            if has_internal_lb:
                # Surgical split
                split_idx = find_split_point(orig_label, val)
                part1, part2 = val[:split_idx], val[split_idx:]
                lb_tag = '<lb break="no" precision="low"/>'
                token_xml = f'<{tag} xml:id="{w_id}">{gap_open}{escape(part1)}{lb_tag}{escape(part2)}{gap_close}</{tag}>'
                tokens_on_line = 0  # Force wrap after an internal lb
            else:
                token_xml = f'<{tag} xml:id="{w_id}">{gap_open}{escape(val)}{gap_close}</{tag}>'

            body_parts.append(token_xml)

            # Beautification wrapping
            if tokens_on_line >= 10:
                body_parts.append("\n        ")
                tokens_on_line = 0

        # Preserve any trailing whitespace in the segment
        if prev_end < len(text):
            body_parts.append(escape(text[prev_end:]))

        if orig_label and local_ids:
            resp_attr = ""
            if users_by_id and annot_resp_id and annot_resp_id in users_by_id:
                resp_attr = f' resp="#{escape(users_by_id[annot_resp_id])}"'
            type_attr    = f' type="{escape(span_type)}"'    if span_type    else ''
            subtype_attr = f' subtype="{escape(span_subtype)}"' if span_subtype else ''
            if '\n' in orig_label:
                # Render embedded line breaks (word split across original lines) as <lb/>
                # instead of a raw newline character, mirroring the main token rendering above.
                label_lines = orig_label.split('\n')
                rendered_parts, pos = [], abs_start
                for i, part in enumerate(label_lines):
                    rendered_parts.append(escape(part))
                    pos += len(part)
                    if i < len(label_lines) - 1:
                        alto_id = line_alto_by_start.get(pos + 1)
                        n_attr = f' n="{escape(alto_id)}"' if alto_id else ''
                        rendered_parts.append(f'<lb break="no" precision="low"{n_attr}/>')
                        pos += 1
                orig_label_xml = "".join(rendered_parts)
            else:
                orig_label_xml = escape(orig_label)
            span_entries.append(f'      <span target="{" ".join(local_ids)}"{resp_attr}{type_attr}{subtype_attr}>{orig_label_xml}</span>')

    # Main Loop
    for annot in sorted_annots:
        pos = _get_selector(annot, "TextPositionSelector")
        start, end = pos.get("start", 0), pos.get("end", 0)

        if start > cursor:
            annot_resp_id = None
            process_segment(original_text[cursor:start], abs_start=cursor)

        body = annot.get("body", [{}])[0]
        gap_before = bool(body.get("gap_before"))
        gap_after = bool(body.get("gap_after"))
        if body.get("purpose") == "atr_noise":
            raw_text = original_text[start:end]
            resp_id = annot.get("resp_id")
            resp_attr = ""
            if users_by_id and resp_id and resp_id in users_by_id:
                resp_attr = f' resp="#{escape(users_by_id[resp_id])}"'
            gap_open = "<gap/>" if gap_before else ""
            gap_close = "<gap/>" if gap_after else ""
            for s in sorted(subpart_milestones_by_start):
                if start < s < end:
                    body_parts.append(_milestone_tag(subpart_milestones_by_start[s]) + '\n        ')
            body_parts.append(f'<unclear reason="illegible" cert="low"{resp_attr}>{gap_open}{escape(raw_text)}{gap_close}</unclear>')
        elif body.get("purpose") == "non_resolv_abbr":
            reason = body.get("reason", "other")
            raw_text = original_text[start:end]
            resp_id = annot.get("resp_id")
            resp_attr = ""
            if users_by_id and resp_id and resp_id in users_by_id:
                resp_attr = f' resp="#{escape(users_by_id[resp_id])}"'
            annot_resp_id = resp_id
            pre_len = len(body_parts)
            process_segment(raw_text, orig_label=raw_text, span_type="non_resolv_abbr", span_subtype=reason,
                             abs_start=start, gap_before=gap_before, gap_after=gap_after)
            new_parts = body_parts[pre_len:]
            del body_parts[pre_len:]
            body_parts.append(f'<abbr type="{escape(reason)}"{resp_attr}>' + "".join(new_parts) + '</abbr>')
        else:
            annot_resp_id = annot.get("resp_id")
            semtag = body.get("semtag")
            if semtag in SEMTAG_TAGS:
                pre_len = len(body_parts)
                process_segment(body.get("value", ""), orig_label=original_text[start:end], abs_start=start,
                                 gap_before=gap_before, gap_after=gap_after)
                new_parts = body_parts[pre_len:]
                del body_parts[pre_len:]
                tag = SEMTAG_TAGS[semtag]
                body_parts.append(f'<{tag}>' + "".join(new_parts) + f'</{tag}>')
            else:
                process_segment(body.get("value", ""), orig_label=original_text[start:end], abs_start=start,
                                 gap_before=gap_before, gap_after=gap_after)
        cursor = end

    if cursor < len(original_text):
        process_segment(original_text[cursor:], abs_start=cursor)

    full_body = "".join(body_parts)

    contributor_ids = {a.get("resp_id") for a in sorted_annots if a.get("resp_id")}
    contributor_ids |= {a.get("validated_by") for a in sorted_annots if a.get("validated_by")}
    header = build_tei_header(metadata, users_by_id=users_by_id, contributor_ids=contributor_ids)

    return f'''<TEI xmlns="http://www.tei-c.org/ns/1.0">
{header}
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