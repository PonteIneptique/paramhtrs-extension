# MIT License
#
# Copyright 2020-2021 New York University Abu Dhabi
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import dataclasses
import string
from string import punctuation
from typing import Optional, List, Tuple, Literal, Dict, NamedTuple, Union, Callable
from collections import deque, Counter
from xml.sax.saxutils import escape

import rapidfuzz.distance.Levenshtein as editdistance
import regex as re


MAP_RE_ABBR_SIMPLIFICATION = {
    "ꝓ": "pr",
    "\u1dd1": "ur",
    "⁊": "et",
    "&": "et",
    "ꝑ": "per",
    "ħ": "h",  # For some characters, we need to ensure that a "normal" form is proposed, to reduce distance.
    "ꝙ": "qu",
    "ꝗ": "qu",
    "ẜ": "s",
    "ꝰ": "s",
    "ꝭ": "is",
    "ꝵ": "r",
    "ł": "l",
    "ꝯ": "con",
    "m": "n",  # We simplify m to n
    "ti": "ci"
}
MAP_RE_REG_SIMPLIFICATION = {
    "v": "u",
    "j": "i",
    "m": "n",  # We simplify m to n
    "ti": "ci"
}
# create a single regex matching any key in mapping
RE_ABBR_SIMPLIFICATION = re.compile("|".join(re.escape(k) for k in MAP_RE_ABBR_SIMPLIFICATION.keys()))
RE_REG_SIMPLIFICATION = re.compile("|".join(re.escape(k) for k in MAP_RE_REG_SIMPLIFICATION.keys()))
RE_SPACE = re.compile(r"\s+")

def space_norm(inp: Optional[str]) -> Optional[str]:
    if inp:
        return RE_SPACE.sub(" ", inp)

OperationCode = Literal["s", "d", "i", "n"]
@dataclasses.dataclass
class Alignment:
    source: str
    target: str
    code: OperationCode

    def split(self, at: int) -> List["Alignment"]:
        data = [
            Alignment(source=self.source[:at], target=self.target[:at], code="n"),
            Alignment(source=self.source[at:], target=self.target[at:], code="n")
        ]
        for al in data:
            if al.source != al.target:
                al.code = "s"
        return data

    def __eq__(self, other):
        return self.source == other.source and self.target == other.target and self.code == other.code

    def __iter__(self):
        return iter((self.source, self.target, self.code))

def normalize(token: str) -> str:
    return token.lower().replace("v", "u").replace("j", "i")


def common_hapaxes_normalized(raw: list[str], reg: list[str], max_distance: int) -> list[tuple[str, int, int]]:
    raw_norm = [normalize(t) for t in raw]
    reg_norm = [normalize(t) for t in reg]

    results: list[tuple[str, int, int]] = []
    j = 0
    last_i, last_j =0, 0
    dist = 0
    for i, tok in enumerate(raw_norm):
        # suffix-aware counts
        raw_suffix = raw_norm[i:]
        reg_suffix = reg_norm[j:]

        raw_counts = Counter(raw_suffix)
        reg_counts = Counter(reg_suffix)

        if raw_counts[tok] != 1 or reg_counts.get(tok) != 1:
            continue

        j = reg_norm[last_j:].index(tok) + last_j

        if abs(i - j) <= (max_distance+dist):
            results.append((tok, i, j))
            last_j = j

        j += 1
        dist = abs(j-i)

    return results


def token_splitter(data: str) -> list[str]:
    """ Split token but merge punctuation with previous characters. Takes char of edge cases
    like .w+.

    >>> token_splitter("ceci est un .xxv. d'or n'est-ce pas.Mais est-ce que ça marche ? .s.") == ['ceci', ' ', 'est', ' ', 'un', ' ', '.xxv.', ' ', "d'or", ' ', "n'est-", 'ce', ' ', 'pas.', 'Mais', ' ', 'est-', 'ce', ' ', 'que', ' ', 'ça', ' ', 'marche', ' ', '?', ' ', '.s.']
    True
    >>> token_splitter(" oĩa\uf1ac m̃b ͣ corꝑriᷤᷤ") == [' ', 'oĩa\uf1ac', ' ', 'm̃b ͣ', ' ', 'corꝑriᷤᷤ']
    True
    """
    pattern = re.compile(
        r"""(
        \.\w+\.        # abbreviations like .xxv. or .s.
        |[⁊&\w+'\uf1ac¬]+(?:\s[\uf1ac\u0363-\u036F\u1DDA\u1DDC-\u1DDD\u1DE0\u1DE4\u1DE6\u1DE8\u1DEB\u1DEE\u1DF1\uF02B\uF030\uF033])?  # words with apostrophes/hyphens or space + combining
        |[\.,:;?!-]+           # punctuation
        )""",
        re.VERBOSE
    )

    output = []
    for char in pattern.split(data):
        if not char:
            continue
        if char in string.punctuation:
            if output and output[-1].strip():
                output[-1] += char
                continue
        output.append(char)
    return output


def _compute_operation(
        abbreviated_tokens: List[str],
        normalized_tokens: List[str],
        weight_fns: Dict[str, Union[Callable[[str, str], int], Callable[[str], int]]]
) -> Dict[Tuple[int, int], Tuple[int, OperationCode]]:
    """ Compute operations for both token lists

    :param abbreviated_tokens: Tokens that are abbreviated
    :param normalized_tokens: Tokens that are normalized
    :param weight_fns: Function to weight the value of elements

    Returns:

    """
    abbreviated_tokens = [t.lower() for t in abbreviated_tokens]
    normalized_tokens = [t.lower() for t in normalized_tokens]
    # Cost for each pair of token in the input
    tbl: Dict[Tuple[int, int], Tuple[int, OperationCode]] = {(0, 0): (0, 'n')}

    m = len(abbreviated_tokens)
    n = len(normalized_tokens)

    for i in range(0, m):
        tbl[(i + 1, 0)] = (i + 1, 'd')

    for j in range(0, n):
        tbl[(0, j + 1)] = (j + 1, 'i')

    if m == 0 or n == 0:
        return tbl

    for i in range(0, m):
        for j in range(0, n):
            if abbreviated_tokens[i] == normalized_tokens[j]:
                edit_cost = tbl[(i + 1, j + 1)] = (tbl[(i, j)][0], 'n')
            else:
                edit_cost = (tbl[(i, j)][0] + weight_fns['s'](abbreviated_tokens[i], normalized_tokens[j]), 's')

            insert_cost = (tbl[(i, j + 1)][0] + weight_fns['d'](abbreviated_tokens[i]), 'd')
            delete_cost = (tbl[(i + 1, j)][0] + weight_fns['i'](normalized_tokens[j]), 'i')

            tbl[(i + 1, j + 1)] = min([insert_cost, delete_cost, edit_cost], key=lambda t: t[0])

    return tbl


def _simplify_abbr(s: str) -> str:
    s = RE_ABBR_SIMPLIFICATION.sub(lambda m: MAP_RE_ABBR_SIMPLIFICATION[m.group()], s.lower())
    return s.translate(str.maketrans('', '', string.punctuation))


def _simplify_reg(s: str) -> str:
    s = RE_REG_SIMPLIFICATION.sub(lambda m: MAP_RE_REG_SIMPLIFICATION[m.group()], s.lower())
    return s.translate(str.maketrans('', '', string.punctuation))


def find_prefix_split(src: str, tgt: str) -> int:
    """Return split index k so that src[:k] simplifies to tgt, or -1 if not found.

    >>> find_prefix_split('⁊si', 'et')
    1
    >>> find_prefix_split('laloy', 'la')
    2
    >>> find_prefix_split('abc', 'xyz')
    -1
    """
    tgt_simp = _simplify_reg(tgt)
    if not tgt_simp:
        return -1
    for k in range(1, len(src)):
        if _simplify_abbr(src[:k]) == tgt_simp:
            return k
    return -1


def weighted_edit_distance(abbr, reg):
    """ This function takes into account simple modification between abbr and reg to compute their
    edit distance. Distance is doubled for some reason in the original script ?

    >>> weighted_edit_distance('a', 'a.')
    0.0
    >>> weighted_edit_distance('a', 'a')
    0.0
    >>> weighted_edit_distance('a', 'a')
    0.0
    >>> weighted_edit_distance('ꝑ', 'pero')
    0.5
    """
    abbr = RE_ABBR_SIMPLIFICATION.sub(lambda match: MAP_RE_ABBR_SIMPLIFICATION[match.group(0)], abbr)
    abbr = abbr.translate(str.maketrans('', '', string.punctuation))
    reg = RE_REG_SIMPLIFICATION.sub(lambda match: MAP_RE_REG_SIMPLIFICATION[match.group(0)], reg)
    reg = reg.translate(str.maketrans('', '', string.punctuation))
    return editdistance.distance(abbr, reg) * 2 / max(len(abbr), len(reg), 1)


def _gen_alignments(tokens1, tokens2, reading_order: Literal["rtl", "ltr"] = "rtl"):
    weight_fns = {
        's': weighted_edit_distance,
        'd': lambda x: 1,
        'i': lambda x: 1
    }

    dist_table = _compute_operation(tokens1, tokens2, weight_fns)

    m = len(tokens1)
    n = len(tokens2)

    if reading_order == "rtl":
        # Start from the end
        alignments = deque()
        i = m
        j = n

        while i != 0 or j != 0:
            op = dist_table[(i, j)][1]
            cost = dist_table[(i, j)][0]

            if op == 'n' or op == 's':
                alignments.appendleft((i, j, op, cost))
                i -= 1
                j -= 1

            elif op == 'i':
                alignments.appendleft((None, j, 'i', cost))
                j -= 1

            elif op == 'd':
                alignments.appendleft((i, None, 'd', cost))
                i -= 1
    else:  # ToDo: Fix something here
        # Start from the end
        alignments = list()
        i = 0
        j = 0

        while i < m or j < n:
            op = dist_table[(i, j)][1]
            cost = dist_table[(i, j)][0]

            if op == 'n' or op == 's':
                alignments.append((i, j, op, cost))
                i += 1
                j += 1

            elif op == 'i':
                alignments.append((None, j, 'i', cost))
                j += 1

            elif op == 'd':
                alignments.append((i, None, 'd', cost))
                i += 1


    return alignments


def sub_alignments(orig_toks: List[str], norm_toks: List[str], max_distance=20) -> List:
    """ Using local unique tokens, subsplit two sequences.

    :param orig_toks: Tokens in the original string
    :param norm_toks: Tokens in the normalized string
    :param max_distance:

    >>> sub_alignments(list("1222234456561222"), list("222222234456561222"))
    [(['1', '2', '2', '2', '2', '3'], ['2', '2', '2', '2', '2', '2', '2', '3']), (['4', '4', '5', '6', '5', '6', '1'], ['4', '4', '5', '6', '5', '6', '1']), (['2', '2', '2'], ['2', '2', '2'])]

    """
    orig_toks_simple: list[str] = [el.lower() for el in orig_toks]
    norm_toks_simple: list[str] = [
        el.lower().replace("v", "u").replace("j", "i") for el in norm_toks
    ]

    # Simplify the task by splitting around common happaxes
    out = []

    raw_cursor, reg_cursor = 0, 0
    for tok, raw_id, reg_id in common_hapaxes_normalized(
            orig_toks_simple, norm_toks_simple, max_distance=max_distance
    ):
        raw_subset = orig_toks[raw_cursor:raw_id+1]
        reg_subset = norm_toks[reg_cursor:reg_id+1]

        out.append((raw_subset, reg_subset))

        # Now we clean up.
        raw_cursor = raw_id + 1
        reg_cursor = reg_id + 1

    if raw_cursor < len(orig_toks) and reg_cursor < len(norm_toks):
        out.append((orig_toks[raw_cursor:], norm_toks[reg_cursor:]))

    return out


def reprocess_space_insertion(alignments: List[Alignment]) -> List[Alignment]:
    """Handle space insertions/deletions that require splitting source or target tokens.

    Handles three patterns (applied repeatedly until stable):

    Pattern A — source token starts with target token, insertions follow:
      s(src, tgt_prefix) + i('',' ') + i('', word) + ...
        where src.startswith(tgt_prefix)
      → n(tgt_prefix,tgt_prefix) + i('',' ') + s/n(src_suffix, word) + ...

    Pattern B — same but with an intervening null space in source:
      s(src, tgt_prefix) + n(' ',' ') + i('', word) + i('',' ') + ...
        where src.startswith(tgt_prefix)
      → n(tgt_prefix,tgt_prefix) + i('',' ') + s/n(src_suffix, word) + n(' ',' ') + ...
      (source space re-paired with the i('',' ') that followed word)

    Pattern C — insertion word matches prefix of next substitution's source:
      i('', word) + i('',' ') + s(src, tgt)
        where src.startswith(word)
      → n(word, word) + i('',' ') + s/n(src_suffix, tgt)

    Pattern D — source has trailing punct not in target:
      s(src_punct, tgt)  where src_punct[-1] in punctuation and src_punct[:-1] == tgt
      → n(tgt, tgt) + d(punct, '')
    """
    ops = list(alignments)
    changed = True
    while changed:
        changed = False
        new_ops = []
        i = 0
        while i < len(ops):
            al = ops[i]

            # Pattern D: trailing source punctuation not in target
            if (al.code == "s" and al.source and al.target
                    and len(al.source) > 1 and al.source[-1] in string.punctuation
                    and not al.target[-1] in string.punctuation
                    and al.source[:-1] == al.target):
                new_ops.append(Alignment(al.target, al.target, "n"))
                new_ops.append(Alignment(al.source[-1], "", "d"))
                i += 1
                changed = True
                continue

            # Patterns A & B: s(src, tgt_prefix) where src[:k] simplifies to tgt_prefix
            if (al.code == "s" and al.source and al.target
                    and al.source.strip() and al.target.strip()):
                split_k = find_prefix_split(al.source, al.target)
            else:
                split_k = -1
            if split_k != -1:
                src, tgt_prefix = al.source, al.target
                suffix = src[split_k:]

                prefix_src = src[:split_k]
                prefix_code = "n" if prefix_src == tgt_prefix else "s"

                # Pattern A: immediately followed by i('',' ') then i('', word)
                if (i + 2 < len(ops)
                        and ops[i+1].code == "i" and ops[i+1].source == "" and ops[i+1].target == " "
                        and ops[i+2].code == "i" and ops[i+2].source == ""):
                    word = ops[i+2].target
                    code = "n" if suffix == word else "s"
                    new_ops.append(Alignment(prefix_src, tgt_prefix, prefix_code))
                    new_ops.append(Alignment("", " ", "i"))
                    new_ops.append(Alignment(suffix, word, code))
                    i += 3
                    changed = True
                    continue

                # Pattern B: followed by n(' ',' ') then i('', word) then i('',' ')
                if (i + 3 < len(ops)
                        and ops[i+1].code == "n" and space_norm(ops[i+1].source) == " "
                        and ops[i+2].code == "i" and ops[i+2].source == "" and ops[i+2].target.strip()
                        and ops[i+3].code == "i" and ops[i+3].source == "" and ops[i+3].target == " "):
                    word = ops[i+2].target
                    code = "n" if suffix == word else "s"
                    new_ops.append(Alignment(prefix_src, tgt_prefix, prefix_code))
                    new_ops.append(Alignment("", " ", "i"))          # target space before suffix
                    new_ops.append(Alignment(suffix, word, code))
                    new_ops.append(Alignment(" ", " ", "n"))          # source space re-paired
                    i += 4
                    changed = True
                    continue

            # Pattern C: i('', word) + i('',' ') + s(src, tgt) where src.startswith(word)
            if (al.code == "i" and not al.source and al.target.strip()
                    and i + 2 < len(ops)
                    and ops[i+1].code == "i" and ops[i+1].source == "" and ops[i+1].target == " "
                    and ops[i+2].code == "s" and ops[i+2].source.startswith(al.target)):
                word = al.target
                src2, tgt2 = ops[i+2].source, ops[i+2].target
                suffix2 = src2[len(word):]
                code = "n" if suffix2 == tgt2 else "s"
                new_ops.append(Alignment(word, word, "n"))
                new_ops.append(Alignment("", " ", "i"))
                new_ops.append(Alignment(suffix2, tgt2, code))
                i += 3
                changed = True
                continue

            new_ops.append(ops[i])
            i += 1
        ops = new_ops
    return ops


def merge_insert_delete(alignments: List[Alignment]) -> List[Alignment]:
    """Merge adjacent i('',tgt) + d(src,'') or d(src,'') + i('',tgt) into s(src,tgt).

    Only applies when both src and tgt are non-empty, non-space word tokens.
    i('','cum') + d('ẽ','') -> s('ẽ','cum')
    """
    ops = list(alignments)
    changed = True
    while changed:
        changed = False
        new_ops = []
        i = 0
        while i < len(ops):
            al = ops[i]
            if i + 1 < len(ops):
                nx = ops[i + 1]
                # i + d
                if (al.code == "i" and not al.source and al.target.strip()
                        and nx.code == "d" and not nx.target and nx.source.strip()):
                    new_ops.append(Alignment(nx.source, al.target, "s"))
                    i += 2
                    changed = True
                    continue
                # d + i
                if (al.code == "d" and not al.target and al.source.strip()
                        and nx.code == "i" and not nx.source and nx.target.strip()):
                    new_ops.append(Alignment(al.source, nx.target, "s"))
                    i += 2
                    changed = True
                    continue
            new_ops.append(ops[i])
            i += 1
        ops = new_ops
    return ops


def cancel_mirrored_punct(alignments: List[Alignment]) -> List[Alignment]:
    """Cancel i('', X) + [d(' ','')*] + d(X, '') when X is punctuation.

    This fixes the case where trailing punct ends up in target token (e.g. 'a.')
    but exists separately in source (e.g. 'a' + ' ' + '.'):
      n(a,a) + i('','.') + d(' ','') + d('.','') -> n(a,a) + d(' ','') + n('.','.')
    """
    ops = list(alignments)
    changed = True
    while changed:
        changed = False
        new_ops = []
        i = 0
        while i < len(ops):
            al = ops[i]
            # Look for i('', X) where X is a single punct
            if (al.code == "i" and not al.source
                    and len(al.target) == 1 and al.target in string.punctuation):
                punct = al.target
                # Scan ahead through space deletions to find d(punct, '')
                j = i + 1
                space_dels = []
                while j < len(ops) and ops[j].code == "d" and ops[j].source.strip() == "" and not ops[j].target:
                    space_dels.append(ops[j])
                    j += 1
                if j < len(ops) and ops[j].code == "d" and ops[j].source == punct and not ops[j].target:
                    # Cancel: emit the space deletions, then n(punct, punct)
                    new_ops.extend(space_dels)
                    new_ops.append(Alignment(punct, punct, "n"))
                    i = j + 1
                    changed = True
                    continue
            new_ops.append(ops[i])
            i += 1
        ops = new_ops
    return ops


def align_words(abbreviated: str, regularized: str) -> List[Alignment]:
    """ Align two sequences word to words
    :param abbreviated: Abbreviated content
    :param regularized: Regularized content

    >>> align_words("Au. chou rave de folie", "Av chovrave de folie")
    [Alignment(source='Au.', target='Av', code='s'), Alignment(source=' ', target=' ', code='n'), Alignment(source='chou rave', target='chovrave', code='s'), Alignment(source=' de folie', target=' de folie', code='n')]
    """
    abbreviated = RE_SPACE.sub(" ", abbreviated)
    regularized = RE_SPACE.sub(" ", regularized)
    abbreviated_tokens = token_splitter(abbreviated)
    regularized_tokens = token_splitter(regularized)

    output: List[Alignment] = []
    for (abbr, reg) in sub_alignments(abbreviated_tokens, regularized_tokens):
        alignments = _gen_alignments(abbr, reg)

        output.extend(reprocess_space([
            Alignment(abbr[i - 1] if i else "", reg[j - 1] if j else "", op)
            for i, j, op, _ in alignments
        ]))

    output = reprocess_space_insertion(output)
    output = merge_insert_delete(output)

    idx = 0
    while idx < len(output):
        alignment: Alignment = output[idx]
        if alignment.code == "s" and alignment.source and alignment.target:
            src_ends_punct = alignment.source[-1] in string.punctuation
            tgt_ends_punct = alignment.target[-1] in string.punctuation
            if tgt_ends_punct and len(alignment.target) > 1:
                if src_ends_punct:
                    # Both end with punct: split both at -1
                    output = output[:idx] + alignment.split(-1) + output[idx+1:]
                else:
                    # Target has trailing punct, source doesn't: split it off as insertion
                    code = "n" if alignment.source == alignment.target[:-1] else "s"
                    als = [
                        Alignment(source=alignment.source, target=alignment.target[:-1], code=code),
                        Alignment(source="", target=alignment.target[-1], code="i")
                    ]
                    output = output[:idx] + als + output[idx + 1:]
            # Source trailing punct with no target punct: always keep together
        idx += 1

    # Cancel i('',X) / d(X,'') pairs for the same punctuation char (e.g. a . -> a.)
    output = cancel_mirrored_punct(output)

    for alignment in output:
        if alignment.code == "n" and alignment.source != alignment.target:
            alignment.code = "s"

    new_output = []
    for alignment in output:
        if new_output:
            if alignment.code == "n" and new_output[-1].code == "n":
                new_output[-1].source += alignment.source
                new_output[-1].target += alignment.target
                continue
            elif alignment.code == "d" and new_output[-1].code == "d":
                new_output[-1].source += alignment.source
                new_output[-1].target += alignment.target
                continue
        new_output.append(alignment)
    return new_output


def reprocess_space(
    alignments: List[Alignment]
):
    """ Reprocess a "Jaccard" alignment to deal with space insertion and merge them.
    """
    ops = []
    i = 0
    while i < len(alignments):
        src, tgt, op = alignments[i]
        j = len(ops)
        if src and op == "d": # word is deleted, this is weird
            if src.strip():
                if j >= 2 and (
                    space_norm(ops[j-1].source) == " " or space_norm(ops[j-1].target) == " "
                ) and ops[j-2].code == "s": # Look backwards in ops
                    # There needs to be a space before
                    # And a substitution
                    # We compute the original distance
                    orig_dist = weighted_edit_distance(
                        ops[j-2].source, ops[j-2].target
                    )
                    # We check if we have a reduction of the distance
                    new_string = ops[j-2].source+ops[j-1].source+src
                    new_dist = (weighted_edit_distance(new_string, ops[j-2].target))
                    # If we have, we merge, so we need first to extract the old ops
                    if new_dist < orig_dist:
                        ops, prefix = ops[:-2], ops[-2:]
                        ops.append(
                            Alignment(
                                new_string,
                                prefix[0].target,
                                "s"
                            )
                        )
                        # IF prefix[-1] is space on both ends,
                        # AND it means the space after the word was misaligned.
                        if prefix[-1].source == prefix[-1].target:
                            if i+1 < len(alignments) and alignments[i+1].source == " " and not alignments[i+1].target:
                                ops.append(Alignment(" ", " ", "n"))
                                i += 1
                        i += 1
                        continue
                if i+2 < len(alignments) and (
                    space_norm(alignments[i+1].source) == " " or space_norm(alignments[i+1].target) == " "
                ) and alignments[i+2].code == "s":
                    orig_dist = weighted_edit_distance(
                        alignments[i+2].source, alignments[i+2].target
                    )
                    new_string = src + alignments[i+1].source + alignments[i+2].source
                    new_dist = (weighted_edit_distance(new_string, alignments[i+2].target))
                    if new_dist < orig_dist:
                        ops.append(
                            Alignment(
                                new_string,
                                alignments[i+2].target,
                                "s"
                            )
                        )
                        i += 3
                        continue
                    ops.append(alignments[i])
                else:
                    ops.append(alignments[i])
                i += 1
            else: # Just removed space ?
                ops.append(alignments[i])
                i += 1
        else:
            ops.append(alignments[i])
            i += 1
    return ops

def xml_serialize(operations: List[Alignment]):
    """ Serialized stuff into XML
    """
    # serialize
    out = []
    for op in operations:
        if op.source == op.target:
            out.append(f"<seg>{escape(op.source)}</seg>")
        elif not op.source:
            out.append(f"<seg><reg>{escape(op.target)}</reg></seg>")
        elif op.target is None:
            out.append(f"<seg><orig>{escape(op.source)}</orig></seg>")
        else:
            out.append(f"<seg><orig>{escape(op.source)}</orig><reg>{escape(op.target)}</reg></seg>")
    return "<text>"+"".join(out)+"</text>"

def align_and_markup(raw: str, reg:str) -> str:
    operations = align_words(raw, reg)
    return xml_serialize(operations)
