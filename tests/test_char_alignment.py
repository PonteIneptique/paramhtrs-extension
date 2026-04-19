"""Mirror of test_alignment.py, importing from the new char_alignment module.

All 9 test cases from the original must pass with the same expected values,
confirming that the character-level pipeline produces compatible output.
"""
from app.alignment_types import Alignment
from app.char_alignment import align_words


# There are four kind of alignment: null / match, substitution, insertion, deletion.
# Here are the rules:
# 1. While not necessarily based on a word model alignment, space and punctuation are an activator of string splitting,
#     such as `a d` -> `a b`: Alignment(source='a ', target='a ', code='n'), Alignment(source='d', target='b', code='s')
#     and not Alignment(source='a d', target='a b', code='s')
# 2. Alignment(..., code="n") should not follow each other: if multiple things (punctuation, tokens, spaces, etc.) are null operations
#     then they form a single Alignment: `a b c` -> `a b c`: Alignment(source='a b c', target='a b c', code='n')
# 3. Changes in a token form the basis of substitution, even if it's only lower case
#     Alignment(..., code="s"): Alignment(source='REATOR', target='reator', code='s')
# 4. Changes in punctuation are also Alignment(..., code="s"): Alignment(source='.', target=',', code='s')
# 5. Two edge cases exist for 2+3:
#    5.1. `casa.`->`casa,` is a null operation on `casa` = Alignment(source='casa', target='casa', code='n')
#       and a substitution on Alignment(source='.', target=',', code='s').
#    5.2  `.n.` -> `enim` is a single Alignment(..., code="s") because dots here are
#       deleted and part of the main token: Alignment(source='.n.', target='enim', code='s').
#       Same goes for `G.` -> `Galienus`: Alignment(source='G.', target='Galienus', code='s')
# 6. If a token deletion is followed by a token insertion, it should be a substitution.
# 7. Space insertion is a specific kind of phenomenon that needs to be captured `ab`-> `a b`: Alignment(source='a', target='a', code='n')
#       Alignment(source='', target=' ', code='i') Alignment(source='b', target='b', code='n')
# 8. Space deletion leads to a single token most of the time, except before punctuation
#       8.1 `a b` -> `ab`: Alignment(source="a b", target="ab", code="s")
#       8.2 `a .` -> `a.`: [Alignment(source="a", target="a", code="n"),
#                           Alignment(source=" ", target="", code="d")
#                           Alignment(source=".", target=".", code="n")]


def test_trailing_punctuation():
    """
    Tests the trailing-punctuation splitting rules:

    - Both tokens end with different punctuation → split: s(word,word) + s(p1,p2)
    - Only target has trailing punctuation   → split: s/n(word,word) + i('',p)
    - Only source has trailing punctuation   → keep as one substitution (can't
      distinguish abbreviation dots from sentence dots, e.g. `motũ.` vs `G.`)
    - Both tokens end with the same punctuation → split: s/n(word,word) + n(p,p)
    """
    test_cases = [
        # Both end with different punct → split both
        ("renouari.", "renovari,", [
            Alignment("renouari", "renovari", "s"),
            Alignment(".", ",", "s"),
        ]),
        # Only target ends with comma → split off as insertion
        ("qs", "quaesumus,", [
            Alignment("qs", "quaesumus", "s"),
            Alignment("", ",", "i"),
        ]),
        # Only target ends with period → split off as insertion
        ("subiecti", "subjecti.", [
            Alignment("subiecti", "subjecti", "s"),
            Alignment("", ".", "i"),
        ]),
        # Both end with same period → split: substitution + null
        ("iustitia.", "justitiam.", [
            Alignment("iustitia", "justitiam", "s"),
            Alignment(".", ".", "n"),
        ]),
        # Both end with different punct, word part identical → null + substitution
        ("casa.", "casa,", [
            Alignment("casa", "casa", "n"),
            Alignment(".", ",", "s"),
        ]),
        # Source == target[:-1], target has trailing period → null + insertion
        ("a", "a.", [
            Alignment("a", "a", "n"),
            Alignment("", ".", "i"),
        ]),
        # Source has trailing punct with close match → keep as single substitution
        # (cannot reliably distinguish abbreviation dot from sentence dot)
        ("fiance.", "fiances", [
            Alignment("fiance.", "fiances", "s"),
        ]),
        # Source abbreviation dot → keep as single substitution (rule 5.2)
        ("motũ.", "motum", [
            Alignment("motũ.", "motum", "s"),
        ]),
        ("G.", "Galienus", [
            Alignment("G.", "Galienus", "s"),
        ]),
    ]

    for source, target, expected in test_cases:
        result = align_words(source, target)
        assert result == expected, (
            f"Failed trailing-punct alignment for: {source!r} -> {target!r}\n"
            f"  expected: {expected}\n"
            f"  got:      {result}"
        )


def test_alignment_rules():
    """
    Tests the alignment logic against the 7 core business rules provided.
    """
    test_cases = [
        # Rule 1: Consecutive null operations merge
        ("a b c", "a b c", [Alignment("a b c", "a b c", "n")]),

        # Rule 2: Token changes are substitutions
        ("REATOR", "reator", [Alignment("REATOR", "reator", "s")]),

        # Rule 3: Punctuation changes are substitutions
        (".", ",", [Alignment(".", ",", "s")]),

        # Rule 4.1: Mixed match and punctuation substitution
        ("casa.", "casa,", [
            Alignment("casa", "casa", "n"),
            Alignment(".", ",", "s")
        ]),

        # Rule 4.2: Abbreviations/deletions within tokens are single substitutions
        (".n.", "enim", [Alignment(".n.", "enim", "s")]),
        ("G.", "Galienus", [Alignment("G.", "Galienus", "s")]),

        # Rule 5: Deletion + Insertion = Substitution
        # (Assuming the engine interprets 'old' -> 'new' as 's' rather than 'd' then 'i')
        ("word", "verb", [Alignment("word", "verb", "s")]),

        # Rule 6: Space insertion (Special 'i' case)
        ("ab", "a b", [
            Alignment("a", "a", "n"),
            Alignment("", " ", "i"),
            Alignment("b", "b", "n")
        ]),

        # Rule 7.1: Space deletion in tokens
        ("a b", "ab", [Alignment("a b", "ab", "s")]),

        # Rule 7.2: Space deletion before punctuation
        ("a .", "a.", [
            Alignment("a", "a", "n"),
            Alignment(" ", "", "d"),
            Alignment(".", ".", "n")
        ])
    ]

    for source, target, expected in test_cases:
        result = align_words(source, target)
        assert result == expected, f"Failed Rule Alignment for: {source!r} -> {target!r}\n  expected: {expected}\n  got:      {result}"


def test_short_sentence_space_insertion():
    abbr, reg = "ione laloy desiuis.", "ione la loi des iuis"
    expected = [
        Alignment(source='ione la', target='ione la', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='loy', target='loi', code='s'),
        Alignment(source=' des', target=' des', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='iuis', target='iuis', code='n'),
        Alignment(source='.', target='', code='d')
    ]
    assert abbr.replace("\n", " ") == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    als = align_words(abbr, reg)
    assert als == expected, (
        f"Failed short-sentence space-insertion\n"
        f"  expected: {expected}\n"
        f"  got:      {als}"
    )


def test_elision_curly_apostrophe():
    """Elision with U+2019 (curly right single quotation mark) must yield a single
    substitution, not Insertion(s) + Insertion(') + Sub(stem, expanded)."""
    test_cases = [
        # sassemblerẽt → s'assemblerent: treated as one token
        (
            "sassemblerẽt",
            "s\u2019assemblerent",
            [Alignment("sassemblerẽt", "s\u2019assemblerent", code="s")],
        ),
        # nestoit → n'estoit
        (
            "nestoit",
            "n\u2019estoit",
            [Alignment("nestoit", "n\u2019estoit", code="s")],
        ),
        # qil → qu'il: one token on each side
        (
            "qil",
            "qu\u2019il",
            [Alignment("qil", "qu\u2019il", code="s")],
        ),
        # In context: surrounding null ops must not be affected
        (
            "il sassemblerẽt la",
            "il s\u2019assemblerent la",
            [
                Alignment("il ", "il ", code="n"),
                Alignment("sassemblerẽt", "s\u2019assemblerent", code="s"),
                Alignment(" la", " la", code="n"),
            ],
        ),
    ]

    for source, target, expected in test_cases:
        result = align_words(source, target)
        assert result == expected, (
            f"Failed elision alignment for: {source!r} -> {target!r}\n"
            f"  expected: {expected}\n"
            f"  got:      {result}"
        )


def test_elision_space_after_apostrophe():
    """Model may produce "s' assemblerent" (space after) or "n ' estoit"
    (spaces both sides).  All variants must collapse to a single substitution."""
    test_cases = [
        # Space after apostrophe only
        (
            "sassemblerẽt",
            "s' assemblerent",
            [Alignment("sassemblerẽt", "s'assemblerent", code="s")],
        ),
        # Spaces both sides of apostrophe
        (
            "nestoit",
            "n ' estoit",
            [Alignment("nestoit", "n'estoit", code="s")],
        ),
        # Curly apostrophe with trailing space
        (
            "sassemblerẽt",
            "s\u2019 assemblerent",
            [Alignment("sassemblerẽt", "s\u2019assemblerent", code="s")],
        ),
        # In context: surrounding null ops must be preserved
        (
            "il nestoit la",
            "il n ' estoit la",
            [
                Alignment("il ", "il ", code="n"),
                Alignment("nestoit", "n'estoit", code="s"),
                Alignment(" la", " la", code="n"),
            ],
        ),
    ]
    for source, target, expected in test_cases:
        result = align_words(source, target)
        assert result == expected, (
            f"Failed elision-space alignment for: {source!r} -> {target!r}\n"
            f"  expected: {expected}\n"
            f"  got:      {result}"
        )


def test_tironian_et_fused_and_linebreak_word():
    """⁊si must split into ⁊ + si (not fuse into one token).
    ta\\nnt (word spanning a line break) must merge into one substitution unit."""
    abbr = "moit nule criature tãt.⁊si lamoit ta\nnt cõme son heritier ⁊qi"
    reg  = "moit nule creature tant et si l amoit tant comme son heritier et qui"
    expected = [
        Alignment(source='moit nule ',  target='moit nule ',  code='n'),
        Alignment(source='criature',    target='creature',    code='s'),
        Alignment(source=' ',           target=' ',            code='n'),
        Alignment(source='tãt.',        target='tant',         code='s'),
        Alignment(source='',            target=' ',            code='i'),
        Alignment(source='⁊',           target='et',           code='s'),
        Alignment(source='',            target=' ',            code='i'),
        Alignment(source='si l',        target='si l',         code='n'),
        Alignment(source='',            target=' ',            code='i'),
        Alignment(source='amoit ',      target='amoit ',       code='n'),
        Alignment(source='ta nt',       target='tant',         code='s'),
        Alignment(source=' ',           target=' ',            code='n'),
        Alignment(source='cõme',        target='comme',        code='s'),
        Alignment(source=' son heritier ', target=' son heritier ', code='n'),
        Alignment(source='⁊',           target='et',           code='s'),
        Alignment(source='',            target=' ',            code='i'),
        Alignment(source='qi',          target='qui',          code='s'),
    ]
    assert abbr.replace('\n', ' ') == ''.join(a.source for a in expected)
    assert reg == ''.join(a.target for a in expected)
    result = align_words(abbr, reg)
    assert result == expected, (
        f"Failed ⁊si / ta\\nnt alignment\n"
        f"  expected: {expected}\n"
        f"  got:      {result}"
    )


def test_longer_space_insertion_punctuation_deletion():
    abbr = """ione laloy desiuis.:Qins aoroient ⁊ leruoient
les ydoles ⁊si feisoient faire ymages demeintes
camblances ou il auoient lor fiance. """
    reg = """ione la loi des iuis ains aoroient et largioient les ydeles et si fesoient faire ymages de maintes semblances o il auoient lor fiances """
    expected = [
        Alignment(source='ione la', target='ione la', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='loy', target='loi', code='s'),
        Alignment(source=' des', target=' des', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='iuis', target='iuis', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='.:', target='', code='d'),
        Alignment(source='Qins', target='ains', code='s'),
        Alignment(source=' aoroient ', target=' aoroient ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='leruoient', target='largioient', code='s'),
        Alignment(source=' les ', target=' les ', code='n'),
        Alignment(source='ydoles', target='ydeles', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='si ', target='si ', code='n'),
        Alignment(source='feisoient', target='fesoient', code='s'),
        Alignment(source=' faire ymages de', target=' faire ymages de', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='meintes', target='maintes', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='camblances', target='semblances', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ou', target='o', code='s'),
        Alignment(source=' il auoient lor ', target=' il auoient lor ', code='n'),
        Alignment(source='fiance.', target='fiances', code='s'),
        Alignment(source=' ', target=' ', code='n')
    ]
    assert abbr.replace("\n", " ") == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    als = align_words(abbr, reg)
    assert als == expected, (
        f"Failed longer-space-insertion test\n"
        f"  expected: {expected}\n"
        f"  got:      {als}"
    )
