"""Tests for annotation offset correctness.

These tests verify that the TextPositionSelector start/end values produced by
align_to_annotations and align_to_annotations_from_chunks exactly match the
corresponding slice of the original (reference) text.

The key invariant under test:
    original_text[annot.start : annot.end] == annot.TextQuoteSelector.exact

A failure means Recogito will highlight the wrong characters in the source panel.
"""

import pytest
from app.annot_utils import align_to_annotations, align_to_annotations_from_chunks


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
    from app.bp_norm import _split_on_punct

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
    from app.bp_norm import _split_on_punct

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
