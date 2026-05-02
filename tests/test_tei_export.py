"""Tests for build_tei_from_annotations output."""

import pytest
from app.annot_utils import build_tei_from_annotations


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_annot(text, start, end, value, purpose, reason=None):
    from uuid import uuid4
    aid = str(uuid4())
    body = {"type": "TextualBody", "value": value, "purpose": purpose}
    if reason:
        body["reason"] = reason
    return {
        "id": aid,
        "type": "Annotation",
        "body": [body],
        "target": {
            "annotation": aid,
            "selector": [
                {"type": "TextPositionSelector", "start": start, "end": end},
                {"type": "TextQuoteSelector", "exact": text[start:end],
                 "prefix": text[max(0, start - 5):start],
                 "suffix": text[end:end + 5]},
            ],
        },
    }


def _body(tei: str) -> str:
    """Extract the <body><p> content from a TEI string."""
    import re
    m = re.search(r'<body>\s*<p>\s*(.*?)\s*</p>\s*</body>', tei, re.DOTALL)
    return m.group(1).strip() if m else tei


# ── Spacing fixes ─────────────────────────────────────────────────────────────

def test_space_between_words_preserved():
    """A single space between words appears as a space in the body (not doubled)."""
    text = "foo bar"
    result = _body(build_tei_from_annotations(text, []))
    assert '<w xml:id="w1">foo</w> <w xml:id="w2">bar</w>' in result


def test_no_space_when_adjacent_in_original():
    """Punctuation directly adjacent to a word has no added space."""
    text = "foo,bar"
    result = _body(build_tei_from_annotations(text, []))
    assert '<w xml:id="w1">foo</w><pc xml:id="w2">,</pc><w xml:id="w3">bar</w>' in result


def test_space_after_comma_preserved():
    """'foo, bar' keeps the space after the comma."""
    text = "foo, bar"
    result = _body(build_tei_from_annotations(text, []))
    assert '<pc xml:id="w2">,</pc> <w xml:id="w3">bar</w>' in result


def test_annotation_gap_space_preserved():
    """A single space between two adjacent annotations appears in the body."""
    text = "foo bar"
    a1 = _make_annot(text, 0, 3, "FOO", "normalizing")
    a2 = _make_annot(text, 4, 7, "BAR", "normalizing")
    result = _body(build_tei_from_annotations(text, [a1, a2]))
    # The space at position 3 comes from the gap between annotations
    assert "</w> <w" in result or "</w> <pc" in result


def test_no_extra_space_adjacent_annotations():
    """Two directly adjacent annotations (no gap) produce no space in body."""
    text = "foobar"
    a1 = _make_annot(text, 0, 3, "FOO", "normalizing")
    a2 = _make_annot(text, 3, 6, "BAR", "normalizing")
    result = _body(build_tei_from_annotations(text, [a1, a2]))
    # No space between the closing and opening tag
    assert "</w><w" in result or "</w><pc" in result


# ── Non-resolvable abbreviation ───────────────────────────────────────────────

def test_non_resolv_abbr_wraps_in_abbr_tag():
    """non_resolv_abbr purpose wraps word tokens in <abbr type=...>."""
    text = "Joh de Paris"
    a = _make_annot(text, 0, 3, "Joh", "non_resolv_abbr", reason="persName")
    result = _body(build_tei_from_annotations(text, [a]))
    assert '<abbr type="persName">' in result
    assert '<w xml:id="w1">Joh</w>' in result
    assert result.startswith('<abbr type="persName"><w xml:id="w1">Joh</w></abbr>')


def test_non_resolv_abbr_reason_in_standoff():
    """non_resolv_abbr adds type/subtype to the standoff span."""
    text = "Joh de Paris"
    a = _make_annot(text, 0, 3, "Joh", "non_resolv_abbr", reason="persName")
    result = build_tei_from_annotations(text, [a])
    assert 'type="non_resolv_abbr"' in result
    assert 'subtype="persName"' in result


def test_non_resolv_abbr_default_reason():
    """non_resolv_abbr without a reason uses 'other'."""
    text = "smth else"
    a = _make_annot(text, 0, 4, "smth", "non_resolv_abbr")
    result = build_tei_from_annotations(text, [a])
    assert '<abbr type="other">' in result
    assert 'subtype="other"' in result


def test_non_resolv_abbr_orgName():
    """orgName reason renders correctly."""
    text = "SNCF et autres"
    a = _make_annot(text, 0, 4, "SNCF", "non_resolv_abbr", reason="orgName")
    result = _body(build_tei_from_annotations(text, [a]))
    assert '<abbr type="orgName">' in result


def test_non_resolv_abbr_placeName():
    """placeName reason renders correctly."""
    text = "Pars magna"
    a = _make_annot(text, 0, 4, "Pars", "non_resolv_abbr", reason="placeName")
    result = _body(build_tei_from_annotations(text, [a]))
    assert '<abbr type="placeName">' in result


def test_non_resolv_abbr_followed_by_normal_text():
    """Tokens after a non_resolv_abbr are still numbered correctly."""
    text = "Joh de Paris"
    a = _make_annot(text, 0, 3, "Joh", "non_resolv_abbr", reason="persName")
    result = _body(build_tei_from_annotations(text, [a]))
    # w2 should be 'de', w3 should be 'Paris'
    assert '<w xml:id="w2">de</w>' in result
    assert '<w xml:id="w3">Paris</w>' in result


def test_normalizing_annotation_unchanged():
    """Regular normalizing annotation is unaffected by the new logic."""
    text = "abbr full"
    a = _make_annot(text, 0, 4, "abbr", "normalizing")
    result = _body(build_tei_from_annotations(text, [a]))
    assert '<w xml:id="w1">abbr</w>' in result
    assert 'abbr type' not in result


def test_atr_noise_unchanged():
    """atr_noise still produces <unclear>."""
    text = "???"
    a = _make_annot(text, 0, 3, "???", "atr_noise")
    result = _body(build_tei_from_annotations(text, [a]))
    assert '<unclear reason="illegible"' in result
