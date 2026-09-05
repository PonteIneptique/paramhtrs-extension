import os

from flask import current_app

from penelopy import Backend
from penelopy.models import load_model


def get_model():
    """Load the normalization model, preferring the ONNX-quantized export
    produced by `flask quantize` (app/bp_quantize.py) when present at
    MODEL_QUANTIZED_PATH. Falls back to the original HuggingFace checkpoint if
    `flask quantize` has never been run.

    Both backends are penelopy NormalizerModel instances, so callers just use
    `.normalize([...]) -> [...]` either way.
    """
    quantized_path = current_app.config["MODEL_QUANTIZED_PATH"]
    if os.path.isdir(quantized_path) and os.listdir(quantized_path):
        return load_model(
            current_app.config["SEQ2SEQ_MODEL"],
            backend=Backend.ONNX,
            quantized_path=quantized_path,
        )
    return load_model(current_app.config["SEQ2SEQ_MODEL"])


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
