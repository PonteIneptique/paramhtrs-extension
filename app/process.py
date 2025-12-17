import difflib
import unicodedata
from typing import List, Tuple, Optional
from xml.sax.saxutils import escape
import os

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from flask import current_app, Response


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
            out.append(f"<seg>{escape(o)}</seg>")
        elif o is None:
            out.append(f"<seg><reg>{escape(r)}</reg></seg>")
        elif r is None:
            out.append(f"<seg><orig>{escape(o)}</orig></seg>")
        else:
            out.append(f"<seg><orig>{escape(o)}</orig><reg>{escape(r)}</reg></seg>")
    return "<text>"+"".join(out)+"</text>"


def get_model_and_tokenizer() -> Tuple[AutoModelForSeq2SeqLM, AutoTokenizer]:
    return (
        AutoModelForSeq2SeqLM.from_pretrained(current_app.config["SEQ2SEQ_MODEL"]),
        AutoTokenizer.from_pretrained(current_app.config["SEQ2SEQ_MODEL"])
    )


def from_xml_to_tei(xml_string: str, plaintext: bool=False) -> str:
    import saxonche
    processor = saxonche.PySaxonProcessor()
    xslt_proc = processor.new_xslt30_processor()
    xslt_proc.set_cwd(".")
    transformer = xslt_proc.compile_stylesheet(stylesheet_file=os.path.join(
        current_app.root_path, "..",
        "utils", "to_tei.xsl"
    ))
    document_builder = processor.new_document_builder()
    source_node = document_builder.parse_xml(xml_text=xml_string)
    value = transformer.transform_to_string(
        xdm_node=source_node
    )
    if plaintext:
        transformer2 = xslt_proc.compile_stylesheet(stylesheet_file=os.path.join(
            current_app.root_path, "..",
            "utils", "to_plaintext.xsl"
        ))
        value = document_builder.parse_xml(xml_text=value)
        value = transformer2.transform_to_string(xdm_node=value)
    return str(value)
