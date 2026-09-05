"""Tests for the deterministic over-normalization filter.

Ported from step 2 of penelopy's scripts/clean_overnormalization.py (a repo-only
training-data tool, not part of the installed package): the PEN task definition
requires punctuation to be preserved exactly as in the source, so a model edit
whose every side is punctuation is over-normalization and is dropped without any
judgement call.
"""
import pytest

from app.annot_utils import (
    discard_punctuation_changes,
    has_abbreviation_marker,
    is_pure_punctuation_annotation,
)


def _annot(purpose, exact="", value=""):
    return {
        "id": "x",
        "type": "Annotation",
        "body": [{"type": "TextualBody", "value": value, "purpose": purpose}],
        "target": {"selector": [
            {"type": "TextPositionSelector", "start": 0, "end": len(exact)},
            {"type": "TextQuoteSelector", "exact": exact, "prefix": "", "suffix": ""},
        ]},
    }


# ── pure punctuation: dropped ────────────────────────────────────────────────

@pytest.mark.parametrize("annot", [
    _annot("normalizing", ".", ","),      # modernized sentence punctuation
    _annot("normalizing", ".", ";"),
    _annot("normalizing", ". ", ", "),    # trailing space must not shield it
    _annot("insertion", "", "."),         # punctuation the source never had
    _annot("insertion", "", ","),
    _annot("normalizing", "·", "."),
])
def test_pure_punctuation_is_discarded(annot):
    assert is_pure_punctuation_annotation(annot) is True


# ── real resolutions: kept ───────────────────────────────────────────────────

@pytest.mark.parametrize("annot", [
    _annot("normalizing", "⁊", "et"),        # abbreviation glyph
    _annot("deletion", "⁊", ""),
    _annot("deletion", ".", ""),             # scribal punctus — see below
    _annot("normalizing", "sem̃", "semen"),   # combining mark
    _annot("normalizing", "reliqͥ", "reliqui"),
    _annot("insertion", "", "et"),           # alphanumeric insertion
    _annot("normalizing", "pisce", "pisces"),
    _annot("normalizing", ".", "et"),        # one side is a real word
])
def test_real_resolutions_are_kept(annot):
    assert is_pure_punctuation_annotation(annot) is False


def test_punctuation_deletions_are_kept():
    """A deleted point may be the scribal punctus resolved away rather than
    modernized punctuation — 35% of these are validated by annotators in the
    production corpus — so it cannot be settled deterministically and is left
    for the annotator. This is a deliberate divergence from penelopy's script,
    which discards deletions too."""
    for exact in (".", ":", "·", "|"):
        assert is_pure_punctuation_annotation(_annot("deletion", exact, "")) is False


def test_whitespace_insertion_is_kept():
    """Inserting a space is word segmentation — a genuine resolution of unspaced
    ATR output — not a punctuation change, even though a space is not
    alphanumeric."""
    assert is_pure_punctuation_annotation(_annot("insertion", "", " ")) is False
    assert is_pure_punctuation_annotation(_annot("deletion", " ", "")) is False


def test_markup_annotations_are_never_touched():
    """A semantic-tag annotation carries no text edit, so it has nothing to
    judge and must survive."""
    assert is_pure_punctuation_annotation(_annot("markup", "Cesar", "")) is False


def test_space_is_excluded_from_abbr_chars():
    """MAP_RE_ABBR_SIMPLIFICATION has " ͣ"-style space+combining keys; the space
    must not leak into ABBR_CHARS or every punctuation edit containing a space
    would look abbreviated."""
    assert has_abbreviation_marker(" ") is False
    assert has_abbreviation_marker("⁊") is True
    assert has_abbreviation_marker("sem̃") is True
    assert has_abbreviation_marker(".") is False


def test_discard_punctuation_changes_partitions_and_preserves_order():
    annots = [
        _annot("normalizing", "⁊", "et"),
        _annot("normalizing", ".", ","),
        _annot("normalizing", "sem̃", "semen"),
        _annot("insertion", "", "."),
        _annot("deletion", ".", ""),
    ]
    kept, dropped = discard_punctuation_changes(annots)
    assert [a["body"][0]["value"] for a in kept] == ["et", "semen", ""]
    assert [a["body"][0]["value"] for a in dropped] == [",", "."]
    assert len(kept) + len(dropped) == len(annots)


def test_end_to_end_on_a_real_alignment():
    """The motivating case: the model modernizes '.' to ',' while genuinely
    resolving the abbreviations around it."""
    from penelopy.aligner import align_to_annotations

    src = "⁊ tunni.⁊ reliqͥ pisce."
    tgt = " tunni, et reliqui pisces"
    kept, dropped = discard_punctuation_changes(align_to_annotations(src, tgt))

    assert [(a["body"][0]["purpose"], a["body"][0]["value"]) for a in dropped] == [
        ("normalizing", ","),
    ]
    kept_values = [a["body"][0]["value"] for a in kept]
    assert "et" in kept_values and "reliqui" in kept_values and "pisces" in kept_values
