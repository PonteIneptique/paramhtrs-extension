import difflib
import json
import unicodedata
from typing import List, Tuple, Optional

import click

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from flask import current_app

from .models import Line, db


def normalize_line(input_text: str, model: AutoModelForSeq2SeqLM, tokenizer: AutoTokenizer) -> str:
    input_text = unicodedata.normalize("NFD", input_text)
    inputs = tokenizer(input_text, return_tensors="pt", padding=True)
    outputs = model.generate(**inputs, max_length=1024)
    decoded = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
    return decoded


def align_to_segs(src: str, tgt: str) -> str:
    sm = difflib.SequenceMatcher(a=src, b=tgt, autojunk=False)

    segments: List[Tuple[Optional[str], Optional[str]]] = []

    cur_src: List[str] = []
    cur_tgt: List[str] = []

    def flush():
        nonlocal cur_src, cur_tgt
        if not cur_src and not cur_tgt:
            return
        segments.append(
            (
                "".join(cur_src) if cur_src else None,
                "".join(cur_tgt) if cur_tgt else None,
            )
        )
        cur_src = []
        cur_tgt = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a = src[i1:i2]
        b = tgt[j1:j2]

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
                cur_src.append(ca)
                ai += 1
            if cb is not None:
                cur_tgt.append(cb)
                bi += 1

    flush()

    # serialize
    out = []
    for o, r in segments:
        if o == r:
            out.append(f"<seg>{o}</seg>")
        elif o is None:
            out.append(f"<seg><reg>{r}</reg></seg>")
        elif r is None:
            out.append(f"<seg><orig>{o}</orig></seg>")
        else:
            out.append(f"<seg><orig>{o}</orig><reg>{r}</reg></seg>")
    return "<text>"+"".join(out)+"</text>"


def get_model_and_tokenizer() -> Tuple[AutoModelForSeq2SeqLM, AutoTokenizer]:
    model_name = "../model-small/"
    return (
        AutoModelForSeq2SeqLM.from_pretrained(model_name),
        AutoTokenizer.from_pretrained(model_name)
    )

# -------------------------
# CLI import function
# -------------------------
@click.command("import-text")
@click.argument("file_path")
def import_text(file_path):
    """Import a plain text file into the DB."""
    model, tokenizer = get_model_and_tokenizer()

    with current_app.app_context():
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                normalized = normalize_line(line, model, tokenizer)
                xml = align_to_segs(line, normalized)
                db.session.add(Line(original_text=line, xml=xml, status='pending', metadata_json=json.dumps({})))
        db.session.commit()
        click.echo(f"Imported {file_path} into DB.")