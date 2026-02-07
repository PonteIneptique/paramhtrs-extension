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

import string
from typing import Optional, List, Tuple, Literal, Dict, Callable, Union
from collections import deque, namedtuple

import rapidfuzz.distance.Levenshtein as editdistance
import regex as re
from app.aligner import common_hapaxes_normalized


MAP_RE_ABBR_SIMPLIFICATION = {
    "ꝓ": "pr",
    "\u1dd1": "ur",
    "⁊": "et",
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

OperationCode = Literal["s", "d", "i", "n"]
Alignment: Tuple[str, str, OperationCode] = namedtuple(
    "Alignment",
    field_names=["source", "target", "code"]
)


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
        |[⁊\w+'\uf1ac]+(?:\s[\uf1ac\u0363-\u036F\u1DDA\u1DDC-\u1DDD\u1DE0\u1DE4\u1DE6\u1DE8\u1DEB\u1DEE\u1DF1\uF02B\uF030\uF033])?  # words with apostrophes/hyphens or space + combining
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
):
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

    m = len(abbreviated_tokens), str
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


def _gen_alignments(tokens1, tokens2):
    weight_fns = {
        's': weighted_edit_distance,
        'd': lambda x: 1,
        'i': lambda x: 1
    }

    dist_table = _compute_operation(tokens1, tokens2, weight_fns)

    m = len(tokens1)
    n = len(tokens2)

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

    return alignments


def sub_alignments(orig_toks: List[str], norm_toks: List[str], max_distance=20) -> List:
    """

    :param orig_toks:
    :param norm_toks:
    :param max_distance:

    """
    orig_toks_simple: list[str] = [el.lower() for el in orig_toks]
    norm_toks_simple: list[str] = [
        el.lower().replace("v", "u").replace("j", "i") for el in norm_toks
    ]

    # Simplify the task by splitting around common happaxes
    out = []

    raw_cursor, reg_cursor = 0, 0

    def get_len(subset: list[str]) -> int:
        return len("".join(subset))

    for tok, raw_id, reg_id in common_hapaxes_normalized(
            orig_toks_simple, norm_toks_simple, max_distance=max_distance
    ):
        raw_subset = orig_toks[raw_cursor:raw_id]
        reg_subset = norm_toks[reg_cursor:reg_id]

        out.append((raw_subset, reg_subset))

        # Now we clean up.
        raw_cursor = raw_id + 1
        reg_cursor = reg_id + 1

    return out


def align_words(abbreviated, regularized):
    abbreviated_tokens = token_splitter(abbreviated)
    regularized_tokens = token_splitter(regularized)

    output: Tuple[Optional[str], Optional[str], Literal['i', 's', 'n', 'd']] = []
    for (abbr, reg) in sub_alignments(abbreviated_tokens, regularized_tokens):
        alignments = _gen_alignments(abbr, reg)

        output.extend([
            Alignment(abbr[i - 1] if i else "", reg[j - 1] if j else "", op)
            for i, j, op, _ in alignments
        ])
    return list(alignments), abbreviated_tokens, regularized_tokens


def reprocess_space(
    alignments: List[Tuple[Optional[str], Optional[str], Literal["s", "d", "i", "n"]]]
):
    """
    """
    ops = []
    i = 0
    while i < len(alignments):
        src, tgt, op = alignments[i]
        j = len(ops)
        if src and op == "d": # word is deleted, this is weird
            if src.strip():
                if j-2 > 0 and (
                    ops[j-1].source == " " or ops[j-1].target == " "
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
                            if alignments[i+1].source == " " and not alignments[i+1].target:
                                ops.append(Alignment(" ", " ", "n"))
                                i += 1
                        i += 1
                        continue
                if i+2 < len(alignments) and (
                    alignments[i+1].source == " " or alignments[i+1].target == " "
                ) and alignments[j+2].code == "s":
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