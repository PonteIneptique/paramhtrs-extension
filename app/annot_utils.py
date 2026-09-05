"""TEI export and annotation-offset bookkeeping — the parts of the old
alignment stack that are specific to this app.

The alignment engine and the W3C Open Annotation builders were extracted into
penelopy (penelopy.aligner) and are re-exported below so existing call sites
keep working. What stays here is what penelopy has no concept of:

  * the TEI builder, which is deliberately kept local until `cert` support
    (CERT_TEI, emitted as @cert on <span>) is upstreamed into
    penelopy.aligner.tei — penelopy's copy is otherwise identical;
  * `document_metadata`, which reads the Document/Folder/Part ORM graph;
  * the offset-remapping helpers, which mutate Annotation ORM rows in place
    after a line deletion.
"""
import re
import unicodedata
from xml.sax.saxutils import escape

from penelopy.aligner.types import MAP_RE_ABBR_SIMPLIFICATION
from penelopy.aligner import (
    align_to_annotations,
    align_one_chunk,
    align_to_annotations_from_chunks,
    apply_annotations_to_text,
)

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

# Certainty of an abbreviation resolution → TEI @cert. The default, 'ocr_fix'
# (a spelling normalisation or ATR correction, which resolves nothing), and
# anything unknown emit no attribute — only a deliberate resolution is graded.
CERT_DEFAULT = "ocr_fix"
CERT_TEI = {
    "informed":  "high",
    "arbitrary": "low",
    "ambiguous": "medium",
}


def _get_selector(annot: dict, selector_type: str) -> dict:
    for sel in annot.get("target", {}).get("selector", []):
        if sel.get("type") == selector_type:
            return sel
    return {}


# ── deterministic over-normalization filter ──────────────────────────────────
#
# Ported from penelopy's scripts/clean_overnormalization.py (step 2), which is a
# repo-only offline tool for cleaning the pen-alignment-pairs training corpus and
# is NOT part of the installed penelopy package — so it has to live here to run
# at inference time.
#
# The PEN task definition requires punctuation to be preserved exactly as in the
# source, so a model edit that *adds* or *modernizes* punctuation is
# over-normalization by definition and can be discarded without any judgement
# call. Punctuation *deletions* are not — see is_pure_punctuation_annotation.
# The rest of that script (spelling modernization) needs an LLM judge and is
# deliberately not ported.

_NOT_ABBR_GLYPHS = {"m", "ti"}
#: Every character appearing in a recognized abbreviation glyph. "m"/"ti" are
#: excluded because they are ordinary letters that the simplification map only
#: lists as *targets* of a normalisation, not as abbreviation marks.
ABBR_CHARS = {
    ch
    for key in MAP_RE_ABBR_SIMPLIFICATION
    if key not in _NOT_ABBR_GLYPHS
    for ch in key
    if not ch.isspace()  # see is_pure_punctuation_annotation
}


def has_abbreviation_marker(text: str) -> bool:
    """True if `text` contains an abbreviation glyph or any combining mark."""
    return any(ch in ABBR_CHARS or unicodedata.combining(ch) for ch in text)


def _annotation_texts(annot: dict) -> list[str]:
    """The text(s) an annotation introduces or removes: the inserted value for
    an insertion, the deleted source text for a deletion, both sides for a
    substitution."""
    body = annot["body"][0] if annot.get("body") else {}
    purpose = body.get("purpose")
    if purpose == "insertion":
        return [body.get("value", "")]
    exact = _get_selector(annot, "TextQuoteSelector").get("exact", "")
    if purpose == "deletion":
        return [exact]
    if purpose == "normalizing":
        return [exact, body.get("value", "")]
    return []


def is_pure_punctuation_annotation(annot: dict) -> bool:
    """True for an edit whose every side is punctuation — no alphanumerics and
    no abbreviation glyph — i.e. over-normalization under PEN rule 5.

    Two deliberate departures from penelopy's script:

    *Deletions are exempt.* The script discards insertions, substitutions and
    deletions alike. Backtested against this corpus, that is right for the first
    two (2474 edits, 1.0% of them ever validated by an annotator) but wrong for
    deletions: 147 of 415 (35%) were deliberately approved. Those are the scribal
    punctus being resolved away — "…nqe il sot[.] ⁊ pot…" — which the PEN
    definition explicitly sanctions ("a period, colon, or point that is itself
    part of an abbreviation mark … is consumed by resolving that abbreviation").
    Whether a given point ends a clause or marks a suspension is exactly the
    judgement call the script's LLM judge exists for, so it cannot be settled
    deterministically and the edit is left for the annotator.

    *Whitespace-only edits are never "pure punctuation".* Inserting a space is
    word segmentation, a genuine resolution of unspaced ATR output. The script
    reaches the same outcome by accident — U+0020 lands in its ABBR_CHARS via
    the " ͣ"-style space+combining keys of MAP_RE_ABBR_SIMPLIFICATION, so
    has_abbreviation_marker(" ") is True there. Here the space keys are stripped
    out of ABBR_CHARS and the case is stated outright, which also makes
    ". " -> ", " get caught (the script keeps it, since the trailing space alone
    makes it look abbreviated).
    """
    body = annot["body"][0] if annot.get("body") else {}
    if body.get("purpose") == "deletion":
        return False
    texts = _annotation_texts(annot)
    if not texts:
        return False
    if all(not text.strip() for text in texts):
        return False  # whitespace-only: word segmentation, not punctuation
    return all(
        text
        and not any(ch.isalnum() for ch in text)
        and not has_abbreviation_marker(text)
        for text in texts
    )


def discard_punctuation_changes(annotations: list) -> tuple[list, list]:
    """Split annotations into (kept, discarded-as-pure-punctuation)."""
    kept, discarded = [], []
    for annot in annotations:
        (discarded if is_pure_punctuation_annotation(annot) else kept).append(annot)
    return kept, discarded


QUOTE_CONTEXT = 10  # chars of prefix/suffix kept in a TextQuoteSelector


def remap_offsets_after_deletion(start: int, end: int, d0: int, d1: int):
    """Map an annotation's (start, end) across a deletion of the character
    range [d0, d1) from the document text.

    Offsets before the cut are untouched, offsets inside it collapse onto d0,
    offsets after it shift left by the deleted length. Returns None when the
    annotation no longer covers any surviving text — i.e. its whole span was
    inside the deleted range (including zero-length insertions anchored there).
    """
    delta = d1 - d0

    def move(x: int) -> int:
        if x <= d0:
            return x
        if x < d1:
            return d0
        return x - delta

    new_start, new_end = move(start), move(end)
    if start == end:
        # Insertion point: it survives only if it was outside the cut.
        return None if d0 < start < d1 else (new_start, new_end)
    if new_start == new_end:
        return None
    return new_start, new_end


def rebuild_quote_selector(row, full_text: str) -> None:
    """Refresh an Annotation row's TextQuoteSelector cache from `full_text`."""
    start, end = row.target_start, row.target_end
    row.target_exact = full_text[start:end]
    row.target_prefix = full_text[max(0, start - QUOTE_CONTEXT):start]
    row.target_suffix = full_text[end:end + QUOTE_CONTEXT]


def apply_deletion_to_annotations(rows: list, d0: int, d1: int, new_full_text: str) -> list:
    """Remap annotation rows in place across a deletion of [d0, d1), rebuilding
    their quote selectors against the post-deletion text. Returns the rows that
    no longer cover any text and should be deleted."""
    dropped = []
    for row in rows:
        remapped = remap_offsets_after_deletion(row.target_start, row.target_end, d0, d1)
        if remapped is None:
            dropped.append(row)
            continue
        row.target_start, row.target_end = remapped
        rebuild_quote_selector(row, new_full_text)
    return dropped


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
                         gap_before=False, gap_after=False, cert=None):
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
            cert_attr    = f' cert="{CERT_TEI[cert]}"' if cert in CERT_TEI else ''
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
            span_entries.append(f'      <span target="{" ".join(local_ids)}"{resp_attr}{type_attr}{subtype_attr}{cert_attr}>{orig_label_xml}</span>')

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
            # Certainty only qualifies resolutions; markup changes nothing and
            # insertions have no source form to be uncertain about. Mirrors
            # isResolution() in static/js/editor-utils.js.
            purpose = body.get("purpose") or "normalizing"
            cert = (body.get("cert") or CERT_DEFAULT) if purpose not in ("markup", "insertion") else None
            if semtag in SEMTAG_TAGS:
                pre_len = len(body_parts)
                process_segment(body.get("value", ""), orig_label=original_text[start:end], abs_start=start,
                                 gap_before=gap_before, gap_after=gap_after, cert=cert)
                new_parts = body_parts[pre_len:]
                del body_parts[pre_len:]
                tag = SEMTAG_TAGS[semtag]
                body_parts.append(f'<{tag}>' + "".join(new_parts) + f'</{tag}>')
            else:
                process_segment(body.get("value", ""), orig_label=original_text[start:end], abs_start=start,
                                 gap_before=gap_before, gap_after=gap_after, cert=cert)
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