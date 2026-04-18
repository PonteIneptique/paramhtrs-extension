"""Character-level alignment with word-boundary reconstruction.

Pipeline (in execution order)
──────────────────────────────
1. Normalise whitespace in both strings (RE_SPACE).
2. Collapse elision spaces in the regularised text (RE_ELISION_SPACE).
3. _abbr_expand(abbreviated)      → (expanded_str, abbr_spans)
4. _reg_normalize(regularized)    → norm_reg_str
5. _edit_dp(expanded, norm_reg)   → (cost_table, op_table)   Wagner–Fischer
6. _traceback(cost, op, src, tgt) → list[CharOp]
7. _group_by_span(char_ops, abbreviated, regularized, abbr_spans)
                                   → list[SpanGroup]
7b. _pull_deletions_before_insertions(span_groups) → list[SpanGroup]
8. _word_boundary_merge(span_groups) → list[Alignment]
9. _trailing_punct_split(alignments) → list[Alignment]
10. _merge_consecutive_nulls(alignments) → list[Alignment]
10b._reorder_insertions_before_deletions(alignments) → list[Alignment]
"""

from __future__ import annotations

import dataclasses
import string
from typing import List, Optional, Tuple

import regex as re

# ── reuse data constants from alignment.py (no algorithm imports) ─────────────
from .alignment import (
    Alignment,
    OperationCode,
    MAP_RE_ABBR_SIMPLIFICATION,
    MAP_RE_REG_SIMPLIFICATION,
    RE_SPACE,
    RE_ELISION_SPACE,
)

# ── constants ─────────────────────────────────────────────────────────────────

# Pre-sorted abbreviation keys (longest first) so we always try the longest
# possible expansion first when scanning character by character.
_ABBR_KEYS: List[str] = sorted(MAP_RE_ABBR_SIMPLIFICATION, key=len, reverse=True)

# Characters that are considered punctuation for trailing-punct split purposes.
_PUNCT: set[str] = set(string.punctuation)


# ── internal data structures ──────────────────────────────────────────────────

@dataclasses.dataclass
class CharOp:
    """A single character-level edit operation.

    Attributes:
        code:    'n' match / 's' substitution / 'i' insertion / 'd' deletion.
        exp_idx: Index into the *expanded* source string (None for insertions).
        reg_idx: Index into the *normalised* regularised string (None for deletions).
    """
    code:    str
    exp_idx: Optional[int]
    reg_idx: Optional[int]


@dataclasses.dataclass
class SpanGroup:
    """One or more consecutive CharOps that share the same original source span.

    After _group_by_span the source text is always a contiguous slice of the
    *original* abbreviated text (before expansion).  Pure insertions from the
    regularised side have source=''.

    Attributes:
        source:             Slice of the original abbreviated text.
        target:             Corresponding characters from the regularised text.
        is_null_space:      True when code=='n' and both source and target are ' '.
        is_space_insertion: True when code=='i' and target==' '.
    """
    source:             str
    target:             str
    is_null_space:      bool
    is_space_insertion: bool


# ── step 1 – abbreviation expansion ──────────────────────────────────────────

def _abbr_expand(text: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Expand abbreviation characters into their ASCII equivalents.

    Walks *text* character-by-character.  At each position we try every key in
    MAP_RE_ABBR_SIMPLIFICATION (longest first); if a key matches we emit each
    character of its expansion paired with the span ``(pos, pos+len(key))``.
    Otherwise we emit the lowercased character paired with span ``(pos, pos+1)``.

    Punctuation and spaces are emitted as-is (not lowercased).

    Returns:
        expanded:   The expanded string used as the DP source.
        abbr_spans: ``abbr_spans[k] = (orig_start, orig_end)`` such that
                    ``expanded[k]`` came from ``text[orig_start:orig_end]``.

    Example::

        _abbr_expand("⁊si")
        # expanded = "etsi"
        # spans    = [(0,1),(0,1),(1,2),(2,3)]
    """
    expanded_chars: List[str] = []
    abbr_spans:     List[Tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        matched = False
        for key in _ABBR_KEYS:
            k_len = len(key)
            if text[i:i + k_len] == key:
                expansion = MAP_RE_ABBR_SIMPLIFICATION[key]
                span = (i, i + k_len)
                for ch in expansion:
                    expanded_chars.append(ch)
                    abbr_spans.append(span)
                i += k_len
                matched = True
                break
        if not matched:
            ch = text[i]
            # Preserve spaces and punctuation as-is; lowercase letters.
            if ch.isalpha():
                expanded_chars.append(ch.lower())
            else:
                expanded_chars.append(ch)
            abbr_spans.append((i, i + 1))
            i += 1
    return "".join(expanded_chars), abbr_spans


# ── step 2 – regularised-text normalisation ───────────────────────────────────

def _reg_normalize(text: str) -> str:
    """Apply MAP_RE_REG_SIMPLIFICATION substitutions and lowercase the result.

    All substitutions are same-length (v→u, j→i, m→n, ti→ci) so the character
    indices in the result correspond 1-to-1 with those in the input.

    The order matters: ``ti→ci`` is applied first to avoid double-application
    of ``i→i`` on the ``i`` of ``ti``.
    """
    # Apply in a careful order: multi-char keys first.
    ordered_keys = sorted(MAP_RE_REG_SIMPLIFICATION, key=len, reverse=True)
    result = list(text.lower())
    i = 0
    n = len(result)
    while i < n:
        matched = False
        for key in ordered_keys:
            k_len = len(key)
            if "".join(result[i:i + k_len]) == key:
                expansion = MAP_RE_REG_SIMPLIFICATION[key]
                for offset, ch in enumerate(expansion):
                    result[i + offset] = ch
                i += k_len
                matched = True
                break
        if not matched:
            i += 1
    return "".join(result)


# ── step 3 – Wagner–Fischer DP ────────────────────────────────────────────────

def _edit_dp(
    src: str,
    tgt: str,
) -> Tuple[List[List[int]], List[List[str]]]:
    """Classic Wagner–Fischer edit-distance DP.

    Costs:
    - 0   : exact match (same char).
    - 1   : deletion or insertion.
    - 1   : substitution between two *non-space* characters, or between two
             *space* characters (including null-space ↔ null-space).
    - 2   : substitution that crosses the space/non-space boundary (i.e. one of
             src[i-1] or tgt[j-1] is a space and the other is not).  Using cost
             2 is equivalent to a delete + insert, which keeps spaces as genuine
             word-boundary signals rather than absorbing them into substitutions.

    Tie-breaking preference (highest priority first): n > s > d > i.
    Exception: when match_cost equals del_cost for a *space-crossing* pair, we
    prefer 'd' over the notional 's' so that the traceback emits explicit
    deletions rather than space-absorbing substitutions.

    Returns:
        cost: ``cost[i][j]`` = edit distance between ``src[:i]`` and ``tgt[:j]``.
        op:   ``op[i][j]``   = operation that produced ``cost[i][j]``.
    """
    m = len(src)
    n = len(tgt)

    # Initialise tables.
    cost = [[0] * (n + 1) for _ in range(m + 1)]
    op   = [[''] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        cost[i][0] = i
        op[i][0]   = 'd'
    for j in range(1, n + 1):
        cost[0][j] = j
        op[0][j]   = 'i'
    op[0][0] = ''

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            s = src[i - 1]
            t = tgt[j - 1]
            is_match      = s == t
            space_crossing = (s == ' ') != (t == ' ')  # XOR: exactly one is space

            if is_match:
                sub_cost = 0
            elif space_crossing:
                sub_cost = 2  # force del + ins; no single-op space crossing
            else:
                sub_cost = 1

            match_cost = cost[i - 1][j - 1] + sub_cost
            del_cost   = cost[i - 1][j]     + 1
            ins_cost   = cost[i][j - 1]     + 1

            best = min(match_cost, del_cost, ins_cost)
            cost[i][j] = best

            # Tie-breaking: n > s > d > i, but for space-crossing pairs prefer
            # 'd' over 's' so that the traceback uses explicit deletions.
            if best == match_cost and is_match:
                op[i][j] = 'n'
            elif best == match_cost and not space_crossing:
                op[i][j] = 's'
            elif best == del_cost:
                op[i][j] = 'd'
            elif best == ins_cost:
                op[i][j] = 'i'
            else:  # match_cost with space_crossing (cost 2) won
                op[i][j] = 's'

    return cost, op


# ── step 4 – traceback ────────────────────────────────────────────────────────

def _traceback(
    cost: List[List[int]],
    op:   List[List[str]],
    src:  str,
    tgt:  str,
) -> List[CharOp]:
    """Walk the DP table from (m,n) to (0,0) and produce the edit script.

    Returns:
        A list of CharOp objects in source order (left to right).
    """
    ops: List[CharOp] = []
    i = len(src)
    j = len(tgt)

    while i > 0 or j > 0:
        o = op[i][j]
        if o in ('n', 's'):
            ops.append(CharOp(code=o, exp_idx=i - 1, reg_idx=j - 1))
            i -= 1
            j -= 1
        elif o == 'd':
            ops.append(CharOp(code='d', exp_idx=i - 1, reg_idx=None))
            i -= 1
        else:  # 'i'
            ops.append(CharOp(code='i', exp_idx=None, reg_idx=j - 1))
            j -= 1

    ops.reverse()
    return ops


# ── step 5 – group char ops by original source span ──────────────────────────

def _group_by_span(
    char_ops:   List[CharOp],
    abbr:       str,
    reg:        str,
    abbr_spans: List[Tuple[int, int]],
) -> List[SpanGroup]:
    """Aggregate char-level ops into SpanGroups keyed on *original* source span.

    Each CharOp whose exp_idx is not None maps to a span in the original
    abbreviated text via abbr_spans.  Multiple expanded characters that came
    from the same original span (e.g. both 'e' and 't' from '⁊') are merged
    into one SpanGroup.

    Pure insertions (exp_idx is None) always produce a standalone SpanGroup
    with source=''.

    The code assigned to each SpanGroup:

    ====================================  ======
    Condition                             code
    ====================================  ======
    source=='' and target!=''             'i'
    source!='' and target==''             'd'
    source (orig) == target               'n'
    otherwise                             's'
    ====================================  ======

    Note: the match comparison is against the *original* source text (abbr),
    not the expanded form, so that e.g. 'm' vs 'n' in the expansion still shows
    as 's' (since 'm'≠'n' in the original), while a plain 'a'→'a' shows as 'n'.
    """
    groups: List[SpanGroup] = []

    # Accumulator for the current span.
    cur_span:    Optional[Tuple[int, int]] = None
    cur_reg_idx: List[Optional[int]]       = []

    def _flush():
        nonlocal cur_span, cur_reg_idx
        if cur_span is None:
            return
        src_text = abbr[cur_span[0]:cur_span[1]]
        tgt_text = "".join(reg[j] for j in cur_reg_idx if j is not None)

        if not src_text and tgt_text:
            code = 'i'
        elif src_text and not tgt_text:
            code = 'd'
        elif src_text == tgt_text:
            code = 'n'
        else:
            code = 's'

        is_null_space      = (code == 'n' and src_text == ' ' and tgt_text == ' ')
        is_space_insertion = (code == 'i' and tgt_text == ' ')

        groups.append(SpanGroup(
            source=src_text,
            target=tgt_text,
            is_null_space=is_null_space,
            is_space_insertion=is_space_insertion,
        ))
        cur_span    = None
        cur_reg_idx = []

    for cop in char_ops:
        if cop.exp_idx is not None:
            span = abbr_spans[cop.exp_idx]
            if span == cur_span:
                cur_reg_idx.append(cop.reg_idx)
            else:
                _flush()
                cur_span    = span
                cur_reg_idx = [cop.reg_idx]
        else:
            # Pure insertion — flush current accumulator, emit standalone group.
            _flush()
            tgt_ch = reg[cop.reg_idx]
            is_space_ins = (tgt_ch == ' ')
            groups.append(SpanGroup(
                source='',
                target=tgt_ch,
                is_null_space=False,
                is_space_insertion=is_space_ins,
            ))

    _flush()
    return groups


# ── step 5b – pull source deletions before space insertions ──────────────────

def _pull_deletions_before_insertions(span_groups: List[SpanGroup]) -> List[SpanGroup]:
    """Move pure source-deletion span groups that follow a space insertion to
    *before* the insertion.

    The Wagner–Fischer traceback visits insertions before deletions at the same
    DP position, so a space insertion in the target can appear in the span-group
    list *before* the deletion of a punctuation character that logically belongs
    to the preceding word.  For example, expanding '⁊' to 'et' in

        tãt.⁊si → tant et si

    produces:  [... n('t'), **SPACE_INS**, d('.'), s('⁊','et'), ...]

    After this step it becomes:  [... n('t'), d('.'), **SPACE_INS**, s('⁊','et'), ...]

    so that the period deletion is flushed with 'tãt.' → 'tant' rather than
    with '⁊' → 'et'.  Only *pure deletions* (source non-empty, target empty)
    immediately following a space insertion are moved; substitutions and null
    span groups are left in place.
    """
    result: List[SpanGroup] = []
    i = 0
    n = len(span_groups)
    while i < n:
        sg = span_groups[i]
        if sg.is_space_insertion:
            # Collect consecutive pure deletions that follow this boundary.
            j = i + 1
            deletions: List[SpanGroup] = []
            while j < n and span_groups[j].source and not span_groups[j].target:
                deletions.append(span_groups[j])
                j += 1
            if deletions:
                # Emit deletions first, then the space insertion.
                result.extend(deletions)
                result.append(sg)
                i = j
            else:
                result.append(sg)
                i += 1
        else:
            result.append(sg)
            i += 1
    return result


# ── step 6 – word-boundary merge ─────────────────────────────────────────────

def _word_boundary_merge(span_groups: List[SpanGroup]) -> List[Alignment]:
    """Merge span groups into word-level Alignment objects.

    Word boundaries are SpanGroups where is_null_space or is_space_insertion is
    True.  Additionally, a *deleted* space (source=' ', target='') acts as a
    word boundary when the following span group's source is entirely punctuation
    (e.g. ``a .`` → ``a.`` should yield ``n('a') + d(' ') + n('.')`` rather
    than the merged ``s('a .', 'a.')``).

    Within each segment (the run of SpanGroups between two boundaries) we:
    - Collect source = ''.join(sg.source for sg in segment)
    - Collect target = ''.join(sg.target for sg in segment)
    - If *any* SpanGroup has code ≠ 'n'  → emit Alignment with the appropriate
      code: 'd' when target=='', 'i' when source=='', else 's'.
    - If *all* SpanGroups have code 'n'  → emit Alignment(source, target, 'n')

    Null spaces    emit as  Alignment(' ', ' ', 'n').
    Space inserts  emit as  Alignment('',  ' ', 'i').
    Deleted spaces before punctuation emit as Alignment(' ', '', 'd').
    """
    alignments: List[Alignment] = []

    def _code_for(sg: SpanGroup) -> str:
        if not sg.source and sg.target:
            return 'i'
        if sg.source and not sg.target:
            return 'd'
        if sg.source == sg.target:
            return 'n'
        return 's'

    def _is_deleted_space(sg: SpanGroup) -> bool:
        return sg.source == ' ' and sg.target == '' and not sg.is_null_space

    def _is_all_punct(sg: SpanGroup) -> bool:
        """True when the span group's source is non-empty and entirely punctuation."""
        return bool(sg.source) and all(c in _PUNCT for c in sg.source)

    segment: List[SpanGroup] = []

    def _flush_segment():
        if not segment:
            return
        src = "".join(sg.source for sg in segment)
        tgt = "".join(sg.target for sg in segment)
        has_edit = any(_code_for(sg) != 'n' for sg in segment)
        if not has_edit:
            code = 'n'
        elif not tgt:
            code = 'd'
        elif not src:
            code = 'i'
        else:
            code = 's'
        alignments.append(Alignment(source=src, target=tgt, code=code))
        segment.clear()

    n_groups = len(span_groups)
    for idx, sg in enumerate(span_groups):
        if sg.is_null_space:
            _flush_segment()
            alignments.append(Alignment(source=' ', target=' ', code='n'))
        elif sg.is_space_insertion:
            _flush_segment()
            alignments.append(Alignment(source='', target=' ', code='i'))
        elif _is_deleted_space(sg):
            # A deleted space acts as a word boundary when it sits before
            # punctuation-only content (e.g. "a ." → "a.").  In that case we
            # flush the current segment, emit the deletion standalone, and let
            # the punctuation form its own segment.  Otherwise (e.g. "a b" →
            # "ab") we fold the deleted space into the current word segment.
            next_sg = span_groups[idx + 1] if idx + 1 < n_groups else None
            if next_sg is not None and _is_all_punct(next_sg):
                _flush_segment()
                alignments.append(Alignment(source=' ', target='', code='d'))
            else:
                segment.append(sg)
        else:
            segment.append(sg)

    _flush_segment()
    return alignments


# ── step 7 – trailing punctuation split ──────────────────────────────────────

def _strip_trailing_punct(s: str) -> Tuple[str, str]:
    """Return ``(body, trailing_punct)`` where ``trailing_punct`` is the
    longest all-punctuation suffix of ``s`` (may be empty)."""
    i = len(s)
    while i > 0 and s[i - 1] in _PUNCT:
        i -= 1
    return s[:i], s[i:]


def _trailing_punct_split(alignments: List[Alignment]) -> List[Alignment]:
    """Split trailing punctuation off substitution alignments.

    Cases handled (in priority order):

    1. Both source and target end with the **same** punctuation character and
       both have non-empty bodies → split: code(body) + n(punct, punct).
       e.g. ``iustitia.`` → ``justitiam.``  gives  s(word,word) + n('.','.').

    2. Both source and target end with **different** punctuation characters and
       both have non-empty bodies → split: code(body) + s(p_src, p_tgt).
       e.g. ``renouari.`` → ``renovari,``  gives  s(word,word) + s('.',',').

    3. Only the target ends with punctuation and the source body is non-empty
       → split: code(body) + i('', p_tgt).
       e.g. ``qs`` → ``quaesumus,``  gives  s(word,word) + i('',',').

    4. Source ends with punctuation, target does not, and the source body
       (source minus trailing punct) exactly equals the target
       → split: n(body, body) + d(p_src, '').
       e.g. ``iuis.`` → ``iuis``  gives  n('iuis') + d('.').

    All other cases are left unchanged.  Notably, when the remaining body after
    stripping trailing punct would be empty (e.g. ``'.' → ','``) no split is
    performed — the whole thing stays as a single substitution.
    """
    result: List[Alignment] = []
    for alm in alignments:
        if alm.code != 's' or len(alm.source) < 1:
            result.append(alm)
            continue

        src, tgt = alm.source, alm.target
        src_tail = src[-1]
        tgt_tail = tgt[-1] if tgt else ''

        src_has_punct = src_tail in _PUNCT
        tgt_has_punct = bool(tgt) and tgt_tail in _PUNCT

        src_body = src[:-1]  # may be empty
        tgt_body = tgt[:-1] if tgt else ''

        if src_has_punct and tgt_has_punct and src_body and tgt_body:
            # Cases 1 and 2: both end with punct, bodies are non-empty.
            body_code = 'n' if src_body == tgt_body else 's'
            result.append(Alignment(source=src_body, target=tgt_body, code=body_code))
            punct_code = 'n' if src_tail == tgt_tail else 's'
            result.append(Alignment(source=src_tail, target=tgt_tail, code=punct_code))
        elif not src_has_punct and tgt_has_punct and tgt_body:
            # Case 3: only target ends with punct.
            body_code = 'n' if src == tgt_body else 's'
            result.append(Alignment(source=src, target=tgt_body, code=body_code))
            result.append(Alignment(source='', target=tgt_tail, code='i'))
        elif src_has_punct and not tgt_has_punct:
            # Case 4: source ends with punct(s), target does not.
            # Strip all trailing punctuation from source; if the body equals
            # the target exactly, emit n(body) + d(trailing_punct).
            src_multi_body, src_trailing = _strip_trailing_punct(src)
            if src_multi_body and src_multi_body == tgt:
                result.append(Alignment(source=src_multi_body, target=tgt, code='n'))
                result.append(Alignment(source=src_trailing, target='', code='d'))
            else:
                result.append(alm)
        else:
            result.append(alm)
    return result


# ── step 9b – reorder space insertions before adjacent deletions ─────────────

def _reorder_insertions_before_deletions(alignments: List[Alignment]) -> List[Alignment]:
    """Ensure space insertions precede adjacent source-content deletions.

    After ``_trailing_punct_split`` a deletion may end up immediately before a
    space insertion that logically belongs before it.  For example,

        [n('iuis'), d('.:'), i('',' '), s('Qins','ains')]

    is reordered to:

        [n('iuis'), i('',' '), d('.:'), s('Qins','ains')]

    This keeps the output consistent with the convention that a word boundary
    (space insertion) is placed at the position where the word ends in the
    source, before any trailing punctuation deletions.

    Multiple consecutive deletions before a space insertion are all moved.
    """
    result = list(alignments)
    i = 0
    while i < len(result):
        alm = result[i]
        if alm.code == 'i' and alm.target == ' ':
            # Find the start of a run of pure deletions immediately before this.
            j = i - 1
            while j >= 0 and result[j].code == 'd' and not result[j].target:
                j -= 1
            # j+1 is the index of the first deletion in the run.
            if j + 1 < i:
                ins = result.pop(i)
                result.insert(j + 1, ins)
                i = j + 2  # skip past insertion and the following deletions
            else:
                i += 1
        else:
            i += 1
    return result


# ── step 10 – merge consecutive nulls ────────────────────────────────────────

def _merge_consecutive_nulls(alignments: List[Alignment]) -> List[Alignment]:
    """Merge adjacent 'n' (match) alignments into a single Alignment.

    Insertions are left in place; only neighbouring nulls are collapsed.
    """
    if not alignments:
        return alignments
    result: List[Alignment] = [alignments[0]]
    for alm in alignments[1:]:
        prev = result[-1]
        if alm.code == 'n' and prev.code == 'n':
            result[-1] = Alignment(
                source=prev.source + alm.source,
                target=prev.target + alm.target,
                code='n',
            )
        else:
            result.append(alm)
    return result


# ── public entry point ────────────────────────────────────────────────────────

def align_words(abbreviated: str, regularized: str) -> List[Alignment]:
    """Align an abbreviated source string against its regularised form.

    Returns a list of :class:`~alignment.Alignment` objects (same output format
    as the word-level ``alignment.align_words``).

    The pipeline is purely character-level followed by a word-boundary
    reconstruction step — no tokeniser is needed.

    Args:
        abbreviated:  Source text, possibly containing abbreviation characters
                      (⁊, ꝑ, ħ, …) and arbitrary Unicode.
        regularized:  Normalised/regularised target text.

    Returns:
        List of Alignment objects in source order.
    """
    # 1. Normalise whitespace.
    abbreviated = RE_SPACE.sub(" ", abbreviated)

    # 2. Collapse elision spaces in the regularised text and normalise.
    regularized = RE_ELISION_SPACE.sub(r"\1\2", regularized)
    regularized = RE_SPACE.sub(" ", regularized)

    # 3. Expand abbreviations in source; build span index.
    expanded, abbr_spans = _abbr_expand(abbreviated)

    # 4. Normalise regularised text for DP comparison.
    norm_reg = _reg_normalize(regularized)

    # 5–6. DP + traceback.
    cost, op_tbl = _edit_dp(expanded, norm_reg)
    char_ops     = _traceback(cost, op_tbl, expanded, norm_reg)

    # 7. Group char ops by original source span.
    span_groups = _group_by_span(char_ops, abbreviated, regularized, abbr_spans)

    # 7b. Move source deletions that follow a space insertion to before it,
    #     so they are absorbed into the preceding word segment.
    span_groups = _pull_deletions_before_insertions(span_groups)

    # 8. Merge into word-level alignments.
    alms = _word_boundary_merge(span_groups)

    # 9. Split trailing punctuation.
    alms = _trailing_punct_split(alms)

    # 10. Merge consecutive nulls.
    alms = _merge_consecutive_nulls(alms)

    # 10b. Ensure space insertions precede adjacent source-content deletions.
    alms = _reorder_insertions_before_deletions(alms)

    return alms
