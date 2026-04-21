"""Shared types and constants used by char_alignment.py."""

from __future__ import annotations

import dataclasses
from typing import List, Literal

import regex as re

MAP_RE_ABBR_SIMPLIFICATION = {
    "ꝓ": "pr",
    "\u1dd1": "ur",
    "⁊": "et",
    "&": "et",
    "ꝑ": "per",
    "ħ": "h",
    "ꝵ": "rum",
    "ꝙ": "qu",
    "ꝗ": "qu",
    "ẜ": "s",
    "ꝰ": "s",
    "ꝭ": "is",
    "ꝵ": "r",
    "ł": "l",
    "ꝯ": "con",
    "m": "n",
    "ti": "ci",
    # Combinings (with variation SPACE + Combining)
    "ͣ": "a",
    " ͣ": "a",
    "ᷨ": "b",
    " ᷨ": "b",
    "ͨ": "c",
    " ͨ": "c",
    "ͩ": "d",
    " ͩ": "d",
    "ͤ": "e",
    " ͤ": "e",
    "ᷫ": "f",
    " ᷫ": "f",
    "ᷚ": "g",
    " ᷚ": "g",
    "ͪ": "h",
    " ͪ": "h",
    "ͥ": "i",
    " ͥ": "i",
    "": "j",
    " ": "j",
    "ᷜ": "k",
    " ᷜ": "k",
    "ᷝ": "l",
    " ᷝ": "l",
    "ͫ": "m",
    " ͫ": "m",
    "ᷠ": "n",
    " ᷠ": "n",
    "ͦ": "o",
    " ͦ": "o",
    "ᷮ": "p",
    " ᷮ": "p",
    "": "q",
    " ": "q",
    "ͬ": "r",
    " ͬ": "r",
    "ᷤ": "s",
    " ᷤ": "s",
    "ͭ": "t",
    " ͭ": "t",
    "ͧ": "u",
    " ͧ": "u",
    "ͮ": "v",
    " ͮ": "v",
    "ᷱ": "w",
    " ᷱ": "w",
    "ͯ": "x",
    " ͯ": "x",
    "": "y",
    " ": "y",
    "ᷦ": "z",
    " ᷦ": "z"
}
MAP_RE_REG_SIMPLIFICATION = {
    "v": "u",
    "j": "i",
    "m": "n",
    "ti": "ci",
}

RE_SPACE = re.compile(r"\s+")
RE_ELISION_SPACE = re.compile(r"(\w) ?(['\u2019\u02BC\u02B9]) ?(?=\w)")

OperationCode = Literal["s", "d", "i", "n"]


@dataclasses.dataclass
class Alignment:
    source: str
    target: str
    code: OperationCode

    def split(self, at: int) -> List["Alignment"]:
        data = [
            Alignment(source=self.source[:at], target=self.target[:at], code="n"),
            Alignment(source=self.source[at:], target=self.target[at:], code="n"),
        ]
        for al in data:
            if al.source != al.target:
                al.code = "s"
        return data

    def __eq__(self, other):
        return (
            self.source == other.source
            and self.target == other.target
            and self.code == other.code
        )

    def __iter__(self):
        return iter((self.source, self.target, self.code))
