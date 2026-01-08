import re
from collections import Counter
from dataclasses import dataclass
import cydifflib as difflib
from typing import Optional
from xml.sax.saxutils import escape


@dataclass
class String:
    raw: str
    reg: str
    processed: bool = False


TOKEN_RE = re.compile(r"\s+|[^\s]+")


def tokenize(s: str) -> list[str]:
    return TOKEN_RE.findall(s)


def normalize(token: str) -> str:
    return token.lower().replace("v", "u").replace("j", "i")


def common_hapaxes_normalized(raw: list[str], reg: list[str], max_distance: int) -> list[tuple[str, int, int]]:
    raw_norm = [normalize(t) for t in raw]
    reg_norm = [normalize(t) for t in reg]

    raw_counts = Counter(raw_norm)
    reg_counts = Counter(reg_norm)

    return sorted([
        (tok, raw_norm.index(tok), reg_norm.index(tok))
        for tok, c in raw_counts.items()
        if c == 1 and reg_counts.get(tok) == 1 and raw_norm.index(tok) - reg_norm.index(tok) <= max_distance
    ], key=lambda x: x[1])


def local_align(raw, reg, max_distance=10):
    raw_toks: list[str] = tokenize(raw)
    reg_toks: list[str] = tokenize(reg)

    # Simplify the task by splitting around common happaxes
    print()
    strings = []

    raw_cursor, reg_cursor = 0, 0

    def get_len(subset: list[str]) -> int:
        return len("".join(subset))

    for tok, raw_id, reg_id in common_hapaxes_normalized(raw_toks, reg_toks, max_distance=max_distance):
        raw_subset = raw_toks[raw_cursor:raw_id]
        reg_subset = reg_toks[reg_cursor:reg_id]

        start_raw = get_len(raw_toks[:raw_cursor])
        end_raw = start_raw + get_len(raw_subset)

        start_reg = get_len(reg_toks[:reg_cursor])
        end_reg = start_reg + get_len(reg_subset)

        local_raw, local_reg = raw[start_raw:end_raw], reg[start_reg:end_reg]
        if local_raw:
            strings.append(String(local_raw, local_reg, processed=local_raw.lower() == local_reg.lower()))
        strings.append(String(raw[end_raw:end_raw + len(tok)], reg[end_reg:end_reg + len(tok)], True))

        raw_cursor, reg_cursor = raw_id + 1, reg_id + 1

    return strings

def process_subalignments(strings: list[String]) -> list[tuple[str, str]]:
    realigned = []
    for string in strings:
        if string.processed:
            realigned.append((string.raw, string.reg))
        else:
            realigned.extend(align_to_segs(string.raw, string.reg))
    return realigned

def align_to_segs(raw: str, reg: str) -> list[tuple[str, str]]:
    sm = difflib.SequenceMatcher(a=raw.lower(), b=reg.lower(), autojunk=False)

    segments: list[tuple[Optional[str], Optional[str]]] = []

    cur_raw: list[str] = []
    cur_reg: list[str] = []

    def flush():
        nonlocal cur_raw, cur_reg
        if not cur_raw and not cur_reg:
            return
        segments.append(
            (
                "".join(cur_raw) if cur_raw else None,
                "".join(cur_reg) if cur_reg else None,
            )
        )
        cur_raw = []
        cur_reg = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a = raw[i1:i2]
        b = reg[j1:j2]

        ai = bi = 0
        while ai < len(a) or bi < len(b):
            ca = a[ai] if ai < len(a) else None
            cb = b[bi] if bi < len(b) else None

            # BOTH are spaces → true boundary
            if ca == " " and cb == " ":
                flush()
                segments.append((" ", " "))
                ai += 1
                bi += 1
                continue

            # otherwise: absorb everything
            if ca is not None:
                cur_raw.append(ca)
                ai += 1
            if cb is not None:
                cur_reg.append(cb)
                bi += 1

    flush()

    return segments

def global_align(raw: str, reg: str) -> list[tuple[str, str]]:
    return process_subalignments(local_align(raw, reg))


def align_and_markup(raw: str, reg:str) -> str:
    segments = global_align(raw, reg)

    # serialize
    out = []
    for raw_chunk, reg_chunk in segments:
        if raw_chunk == reg_chunk:
            out.append(f"<seg>{escape(raw_chunk)}</seg>")
        elif raw_chunk is None:
            out.append(f"<seg><reg>{escape(reg_chunk)}</reg></seg>")
        elif reg_chunk is None:
            out.append(f"<seg><orig>{escape(raw_chunk)}</orig></seg>")
        else:
            out.append(f"<seg><orig>{escape(raw_chunk)}</orig><reg>{escape(reg_chunk)}</reg></seg>")
    return "<text>"+"".join(out)+"</text>"