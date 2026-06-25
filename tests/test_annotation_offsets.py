"""Tests for annotation offset correctness.

These tests verify that the TextPositionSelector start/end values produced by
align_to_annotations and align_to_annotations_from_chunks exactly match the
corresponding slice of the original (reference) text.

The key invariant under test:
    original_text[annot.start : annot.end] == annot.TextQuoteSelector.exact

A failure means Recogito will highlight the wrong characters in the source panel.
"""

import pytest
from app.annot_utils import (
    align_to_annotations,
    align_to_annotations_from_chunks,
    align_one_chunk,
    apply_annotations_to_text,
)
from app.normalize_jobs import normalize_whitespace


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_pos(annot):
    for sel in annot["target"]["selector"]:
        if sel["type"] == "TextPositionSelector":
            return sel["start"], sel["end"]
    raise AssertionError("No TextPositionSelector found")


def _get_exact(annot):
    for sel in annot["target"]["selector"]:
        if sel["type"] == "TextQuoteSelector":
            return sel["exact"]
    raise AssertionError("No TextQuoteSelector found")


def assert_offsets_correct(orig_text, annots, label=""):
    """Assert that every annotation's position selector slices the right text."""
    for a in annots:
        start, end = _get_pos(a)
        exact = _get_exact(a)
        actual = orig_text[start:end]
        assert actual == exact, (
            f"{label}Annotation offset mismatch: "
            f"[{start}:{end}] in orig gives {actual!r}, "
            f"but TextQuoteSelector.exact is {exact!r}"
        )


# ── single-chunk (no separator) ──────────────────────────────────────────────

def test_simple_substitution():
    orig = "ione laloy desiuis"
    reg  = "ione la loi des iuis"
    annots = align_to_annotations(orig, reg)
    assert annots, "Expected at least one annotation"
    assert_offsets_correct(orig, annots, "simple_substitution: ")


def test_special_medieval_chars():
    """⁊ (U+204A Tironian et), ꝑ (U+A751), combining marks."""
    orig = "⁊asermoner ⁊amonest̾"
    reg  = "et a sermoner et amonester"
    annots = align_to_annotations(orig, reg)
    assert annots
    assert_offsets_correct(orig, annots, "medieval_chars: ")


def test_deletion():
    orig = "ione laloy desiuis.:Qins aoroient"
    reg  = "ione la loi des iuis ains aoroient"
    annots = align_to_annotations(orig, reg)
    assert annots
    assert_offsets_correct(orig, annots, "deletion: ")


def test_trailing_punct_split_does_not_overlap_next_annotation():
    """gał. -> Gal.: splits into s('gał','Gal.') + s('.',':').

    The "extend span by one char" heuristic in _alignments_to_annotations
    must not steal the trailing '.' into the 'gał'->'Gal.' annotation just
    because the target happens to end with '.' too -- that same '.' is the
    source of the very next annotation ('.'->':' ), so stealing it produces
    two overlapping TextPositionSelectors over the same character.
    """
    orig = "gał."
    reg = "Gal.:"
    annots = align_to_annotations(orig, reg)
    assert_offsets_correct(orig, annots, "trailing_punct_split: ")

    positions = sorted(_get_pos(a) for a in annots)
    for (start, end), (next_start, next_end) in zip(positions, positions[1:]):
        assert end <= next_start, (
            f"trailing_punct_split: overlapping annotations {(start, end)} "
            f"and {(next_start, next_end)} in {orig!r} -> {reg!r}"
        )


def test_multi_line_single_call():
    """Full text passed directly (lines joined with \\n)."""
    orig = (
        "ione laloy desiuis.:Qins aoroient ⁊ leruoient\n"
        "les ydoles ⁊si feisoient faire ymages demeintes\n"
        "camblances ou il auoient lor fiance. ⁊ si creoiẽt\n"
        "eneles. ne autre diu naoroient ⁊totes les ma"
    )
    reg = (
        "ione la loi des iuis ains aoroient et largioient "
        "les ydeles et si fesoient faire ymages de maintes "
        "semblances o il auoient lor fiances et si creoient "
        "en eles ne autre deu naoroient et totes les ma"
    )
    annots = align_to_annotations(orig, reg)
    assert len(annots) > 10
    assert_offsets_correct(orig, annots, "multi_line_single: ")


# ── chunk mode (separator=\\n, simulates lines mode) ─────────────────────────

def test_chunks_lines_mode():
    lines = [
        "ione laloy desiuis.:Qins aoroient ⁊ leruoient",
        "les ydoles ⁊si feisoient faire ymages demeintes",
        "camblances ou il auoient lor fiance. ⁊ si creoiẽt",
    ]
    regs = [
        "ione la loi des iuis ains aoroient et largioient",
        "les ydeles et si fesoient faire ymages de maintes",
        "semblances o il auoient lor fiances et si creoient",
    ]
    chunks = [{"orig": l, "reg": r} for l, r in zip(lines, regs)]
    full_text = "\n".join(lines)

    annots = align_to_annotations_from_chunks(chunks, separator="\n")
    assert annots
    assert_offsets_correct(full_text, annots, "chunks_lines_mode: ")


def test_irregular_whitespace_run_garbles_reconstruction_without_normalization():
    """Regression for /document/22: a real ALTO line ("py.cito." followed by a
    13-space run before "siłi.") used to desync align_words' internal char
    positions from the offset bookkeeping around it, garbling every
    annotation positioned after that run within the chunk.

    `reg` below is the real comma-project/normalization-byt5-small model's
    actual output for this exact input (captured directly from the model, not
    hand-written), so this reproduces the live failure, not a synthetic one.
    """
    lines = [
        "⁋ Si dolor fũit ĩ stõ młierib dab̾ iera",
        "py.cito.             siłi.⁊ t̾sserã an.",
        "⁋ Exꝑim̃tũ exꝑtũ ad uitiũ pulmonis",
    ]
    orig_with_irregular_whitespace = " ".join(lines)
    reg = (" si dolor fuerit in facto mulieribus, dabis iera publica cito. "
           "Similiter trisseram ante. Experimentum expertum ad vitium pulmonis")

    # Without normalization, the multi-space run shrinks under align_words'
    # internal whitespace collapsing, desyncing every position after it.
    buggy_annots = align_one_chunk(orig_with_irregular_whitespace, reg,
                                    orig_with_irregular_whitespace, 0)
    garbled = apply_annotations_to_text(orig_with_irregular_whitespace, buggy_annots)
    assert garbled != reg  # demonstrates the bug this fix addresses

    # With the fix (document_create normalizes Line.original_text before it
    # ever reaches the chunker/aligner), the run is already collapsed, so
    # align_words' internal collapsing is a no-op and offsets stay in sync.
    fixed_orig = normalize_whitespace(orig_with_irregular_whitespace)
    fixed_annots = align_one_chunk(fixed_orig, reg, fixed_orig, 0)
    assert_offsets_correct(fixed_orig, fixed_annots, "irregular_whitespace: ")
    assert apply_annotations_to_text(fixed_orig, fixed_annots) == reg


def test_chunks_punctuation_mode():
    """Punctuation mode joins lines with space and splits on delimiters."""
    lines = [
        "abc def. ghi jkl",
        "mno pqr ⁊ stu",
    ]
    regs_by_chunk = [
        "abc def ghi jkl",
        "mno pqr et stu",
    ]
    # Simulate what _split_on_punct produces: split "abc def. ghi jkl mno pqr ⁊ stu"
    # on '.' → chunk 0 = "abc def.", chunk 1 = "ghi jkl mno pqr ⁊ stu"
    chunks = [
        {"orig": "abc def.", "reg": "abc def"},
        {"orig": "ghi jkl mno pqr ⁊ stu", "reg": "ghi jkl mno pqr et stu"},
    ]
    full_text = "\n".join(lines)  # how page.full_text is built

    annots = align_to_annotations_from_chunks(chunks, separator=" ")
    # Positions must be valid in the space-joined reference,
    # which shares char indices with the newline-joined full_text
    ref_text = " ".join(c["orig"] for c in chunks)
    assert_offsets_correct(ref_text, annots, "chunks_punct_mode (ref): ")

    # Also verify they point to the right text in the newline-joined full_text
    # (positions 0–8 are identical; position 8 is '\n' vs ' ' but no annotation should land there)
    assert_offsets_correct(full_text, annots, "chunks_punct_mode (full_text): ")


def test_chunks_offset_accumulates_correctly():
    """char_offset must account for both chunk length AND separator length."""
    lines = ["abc", "def", "ghi"]
    regs  = ["ABC", "DEF", "GHI"]
    chunks = [{"orig": l, "reg": r} for l, r in zip(lines, regs)]
    full_text = "\n".join(lines)

    annots = align_to_annotations_from_chunks(chunks, separator="\n")
    # Every line is fully substituted → 3 annotations
    assert len(annots) == 3
    starts = [_get_pos(a)[0] for a in annots]
    assert starts == [0, 4, 8], f"Expected [0, 4, 8], got {starts}"
    assert_offsets_correct(full_text, annots, "offset_accumulation: ")


# ── full real-world sample ────────────────────────────────────────────────────

def test_full_sample_text():
    """Full two-hundred-word medieval extract; zero mismatches expected."""
    orig = (
        "ione laloy desiuis.:Qins aoroient ⁊ leruoient\n"
        "les ydoles ⁊si feisoient faire ymages demeintes\n"
        "camblances ou il auoient lor fiance. ⁊ si creoiẽt\n"
        "eneles. ne autre diu naoroient ⁊totes les ma\n"
        "res auentures ⁊toutes les oeures qi adeu desplei\n"
        "soient estoient encel tenz ꝑles genz deces con\n"
        "trees aemplies. Qant mes sires sains march\n"
        "libencoiz euuangelistes uint en la terre. il\n"
        "trest aune cite qi estoit apelee cyrene.ou il\n"
        "troua genz nees del pais qi auques enten\n"
        "doient abien depluiseurs choses. Il les cou\n"
        "menca apreechier ⁊asermoner ⁊amonest̾\n"
        "la uoie desalu ⁊ꝑson seul sermon ⁊ꝑsa\n"
        "pole sauoit il pluiseurs enfers qi estoient\n"
        "entrepris degranz enfermetez.⁊si garissoit\n"
        "les meziaus.⁊si chacoit les deables fors des\n"
        "cors as homes ⁊as femes ꝑla grace de nostre sig\n"
        "nor.Lipluisor deceus del pais crurent en"
    )
    reg = (
        "ione la loi des iuis ains aoroient et largioient les ydeles et si fesoient faire ymages de "
        "maintes semblances o il auoient lor fiances et si creoient en eles ne autre deu naoroient "
        "et totes les manres auentures et totes les oures qui a deu desplaisoient estoient en celui "
        "tans par les gens de ces contrees aemplies Quant mes sires sains march li banicois "
        "euangelistes uint en la terre il traist a une cite qui estoit apelee cyrene o il troua gens "
        "nees dou pais qui auques entendoient a bien de pluisors choses il les comensa a proecier et "
        "a sermoner et amonester la uoie de salu et par son soul sermon et par sa parole sauoit il "
        "pluisors enfers qui estoient entrepris de grans enfermetes et si guarissoit les mesiaus et "
        "si chassoit les deables fors des cors as homes et as femes par la grace de nnostre ssegnor "
        "Li pluisor de ceaus dou pais criurent en "
    )
    annots = align_to_annotations(orig, reg)
    assert len(annots) > 50, f"Expected >50 annotations, got {len(annots)}"
    assert_offsets_correct(orig, annots, "full_sample: ")


# ── _split_on_punct offset regression ────────────────────────────────────────

def test_split_on_punct_no_spurious_space():
    """`nombre .li` must not be split at the dot: no space exists between '.' and 'l'
    in the original, so splitting there would inject a phantom space into reference_text
    and shift all subsequent annotation offsets by +1.
    """
    from app.normalize_jobs import _split_on_punct

    text = "iot par nombre .li sairz. leur femes"
    chunks = _split_on_punct(text, ["."], min_words=2)

    # Rejoin exactly as align_to_annotations_from_chunks does
    reference = " ".join(chunks)

    # 'li' must be at the same position in reference_text as in the original
    assert text.index("li") == reference.index("li"), (
        f"'li' at {text.index('li')} in original but {reference.index('li')} in "
        f"reference_text — spurious space injected by split inside '.li'"
    )


def test_split_on_punct_still_splits_at_sentence_boundary():
    """A delimiter followed by a real space (sentence boundary) must still split."""
    from app.normalize_jobs import _split_on_punct

    # min_words=3 so it flushes after the first sentence
    text = "abc def ghi. jkl mno pqr"
    chunks = _split_on_punct(text, ["."], min_words=3)
    assert len(chunks) == 2, f"Expected 2 chunks, got {chunks}"
    assert chunks[0] == "abc def ghi."
    assert chunks[1] == "jkl mno pqr"


def test_split_on_punct_offsets_with_chunks():
    """End-to-end: annotations produced from punctuation-mode chunks must have
    correct TextPositionSelector offsets against the newline-joined full_text."""
    from app.annot_utils import align_to_annotations_from_chunks

    # Simulate two lines where 'nombre .li' straddles a potential split point
    lines = [
        "iot par nombre .li sairz.",
        "leur femes",
    ]
    full_text = "\n".join(lines)

    # Simulate what the model might produce
    regs = [
        "iot par nombre . li sairz .",
        "leur femmes",
    ]

    chunks = [{"orig": l, "reg": r} for l, r in zip(lines, regs)]
    annots = align_to_annotations_from_chunks(chunks, separator="\n")
    assert_offsets_correct(full_text, annots, "punct_offset_regression: ")


# ── align_one_chunk / worker equivalence ──────────────────────────────────────

def test_align_one_chunk_matches_bulk_alignment():
    """worker.py calls align_one_chunk per chunk, as each chunk's reg arrives,
    instead of align_to_annotations_from_chunks all at once. The two must
    produce identical annotations for the same input — this is what makes the
    incremental-persistence refactor behavior-preserving."""
    lines = [
        "ione laloy desiuis.:Qins aoroient ⁊ leruoient",
        "les ydoles ⁊si feisoient faire ymages demeintes",
        "camblances ou il auoient lor fiance. ⁊ si creoiẽt",
    ]
    regs = [
        "ione la loi des iuis ains aoroient et largioient",
        "les ydeles et si fesoient faire ymages de maintes",
        "semblances o il auoient lor fiances et si creoient",
    ]
    chunks = [{"orig": l, "reg": r} for l, r in zip(lines, regs)]
    separator = "\n"

    bulk_annots = align_to_annotations_from_chunks(chunks, separator=separator)

    # Simulate the worker: reference_text/char_offset are fixed up front
    # (known from `orig` alone, independent of when each `reg` arrives), then
    # each chunk is aligned on its own as it's "processed".
    reference_text = separator.join(c["orig"] for c in chunks)
    incremental_annots = []
    char_offset = 0
    for idx, chunk in enumerate(chunks):
        incremental_annots.extend(
            align_one_chunk(chunk["orig"], chunk["reg"], reference_text, char_offset)
        )
        char_offset += len(chunk["orig"])
        if idx < len(chunks) - 1:
            char_offset += len(separator)

    def _without_ids(annots):
        out = []
        for a in annots:
            a = dict(a)
            a.pop("id", None)
            a["target"] = {k: v for k, v in a["target"].items() if k != "annotation"}
            out.append(a)
        return out

    assert _without_ids(incremental_annots) == _without_ids(bulk_annots)
    assert_offsets_correct(reference_text, incremental_annots, "align_one_chunk: ")


# ── multi-part punctuation-mode normalization ────────────────────────────────
#
# Regression for: "having multiple parts does not lead to normalizing around
# punct". A Document's full_text joins ALL lines from ALL Parts uniformly
# with "\n" (Document.full_text in app/models.py), so punctuation-mode chunks
# must stay scoped to a single Part — never merging lines across a part
# boundary — while still keeping the same length-preserving "\n"->" "
# substitution trick that lets one separator value be reused across the
# whole flattened chunk list.

def test_api_normalize_batches_stay_within_part():
    """api_normalize's per-part batching (the actual fix) must never merge
    lines from two different parts into the same punctuation-mode chunk."""
    from app.normalize_jobs import _split_on_punct, _enforce_max_bytes

    delimiters = ["."]
    min_words = 5
    parts_lines = [
        ["Hello world.", "This is part one.", "Second line."],
        ["Part two starts here.", "More words to reach the threshold here."],
    ]

    batches = []
    for part_index, orig_lines in enumerate(parts_lines):
        part_chunks = _split_on_punct(" ".join(orig_lines), delimiters, min_words)
        part_chunks = _enforce_max_bytes(part_chunks, 512)
        for chunk in part_chunks:
            batches.append({"part_index": part_index, "chunk": chunk})

    # No chunk should contain text from both parts.
    for batch in batches:
        if batch["part_index"] == 0:
            assert "Part two" not in batch["chunk"]
        else:
            assert "Hello world" not in batch["chunk"]

    # Every chunk must be attributed to exactly the part it came from.
    part0_text = " ".join(b["chunk"] for b in batches if b["part_index"] == 0)
    part1_text = " ".join(b["chunk"] for b in batches if b["part_index"] == 1)
    assert part0_text == " ".join(parts_lines[0])
    assert part1_text == " ".join(parts_lines[1])


def test_align_to_annotations_from_chunks_across_part_boundary():
    """A punctuation-mode chunk spanning multiple original lines within one
    part must still align correctly against the Document-level, newline-
    joined full_text that spans multiple parts."""
    parts_lines = [
        ["Hello wrld. This is prt one.", "Secnd line of part one."],
        ["Prt two strts here. It has mre words."],
    ]
    full_text = "\n".join(line for lines in parts_lines for line in lines)

    # Chunk 0 spans both lines of part 0 (punctuation mode batched them
    # together); chunk 1 is part 1's only line.
    chunks = [
        {"orig": "Hello wrld. This is prt one. Secnd line of part one.",
         "reg": "Hello world. This is part one. Second line of part one."},
        {"orig": "Prt two strts here. It has mre words.",
         "reg": "Part two starts here. It has more words."},
    ]

    annots = align_to_annotations_from_chunks(chunks, separator=" ")
    assert_offsets_correct(full_text, annots, "multi_part_punct: ")

    result = apply_annotations_to_text(full_text, annots)
    assert result == "\n".join(line for lines in [
        ["Hello world. This is part one.", "Second line of part one."],
        ["Part two starts here. It has more words."],
    ] for line in lines)


def test_document_create_subparts_chunks_field():
    """app/bp_document.py's multi-source 'subparts' shape: when an entry
    carries its own 'chunks' (decoupled from per-line Lines, e.g. punctuation
    mode), flat_chunks must come from those chunks, not from per-line
    'expan' — and the resulting annotations must still resolve correctly
    against the multi-part Document.full_text."""
    from app import app
    from app.models import db, Folder, Document, Part, Line, Project, User

    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SECRET_KEY="test-secret",
    )
    with app.app_context():
        db.create_all()
        user = User(username="subparts-chunks-test", password_hash="x")
        db.session.add(user)
        db.session.flush()
        proj = Project(name="P", description="", creator_id=user.id)
        db.session.add(proj)
        db.session.flush()
        folder = Folder(name="F", description="", project_id=proj.id,
                         creator_id=user.id, language="lat")
        db.session.add(folder)
        db.session.flush()

        document = Document(folder_id=folder.id, label="D1", order=1, status="pending")
        db.session.add(document)
        db.session.flush()

        subpart_entries = [
            {"id": "file1.xml", "lines": [
                {"orig": "Hello wrld. This is prt one.", "alto_id": "l1"},
                {"orig": "Secnd line of part one.", "alto_id": "l2"},
            ], "chunks": [
                {"orig": "Hello wrld. This is prt one. Secnd line of part one.",
                 "reg": "Hello world. This is part one. Second line of part one."},
            ]},
            {"id": "file2.xml", "lines": [
                {"orig": "Prt two strts here. It has mre words.", "alto_id": "l3"},
            ], "chunks": [
                {"orig": "Prt two strts here.", "reg": "Part two starts here."},
                {"orig": "It has mre words.", "reg": "It has more words."},
            ]},
        ]
        flat_chunks = []
        for sp_idx, entry in enumerate(subpart_entries):
            part = Part(document_id=document.id, order=sp_idx)
            part.original_filename = entry.get("id")
            db.session.add(part)
            db.session.flush()
            for idx, line_entry in enumerate(entry.get("lines", [])):
                orig = line_entry.get("orig", "").strip()
                line = Line(part_id=part.id, order=idx, original_text=orig,
                            alto_id=line_entry.get("alto_id"))
                db.session.add(line)
            # Mirrors app/bp_document.py: when "chunks" is present, use it
            # instead of building one chunk per line from "expan".
            flat_chunks.extend(entry.get("chunks") or [])
        db.session.flush()
        document.set_annotations(align_to_annotations_from_chunks(flat_chunks, separator=" "))
        db.session.commit()

        assert document.full_text == (
            "Hello wrld. This is prt one.\n"
            "Secnd line of part one.\n"
            "Prt two strts here. It has mre words."
        )
        assert document.normalized_text == (
            "Hello world. This is part one.\n"
            "Second line of part one.\n"
            "Part two starts here. It has more words."
        )
        offsets = document.part_offsets
        assert [o["original_filename"] for o in offsets] == ["file1.xml", "file2.xml"]
        assert_offsets_correct(document.full_text, document.annotations,
                                "document_create_subparts_chunks: ")

        db.session.remove()
        db.drop_all()
