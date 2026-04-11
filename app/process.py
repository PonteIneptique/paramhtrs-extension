import unicodedata
from typing import List, Tuple, Optional, Literal
import os

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from flask import current_app, Response

def normalize_line(input_text: str, model: AutoModelForSeq2SeqLM, tokenizer: AutoTokenizer) -> str:
    input_text = unicodedata.normalize("NFD", input_text)
    print(input_text)
    inputs = tokenizer(input_text, return_tensors="pt", padding=True)
    outputs = model.generate(**inputs, max_length=1024)
    decoded = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
    return decoded


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
