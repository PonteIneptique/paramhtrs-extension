"""`flask quantize` — export SEQ2SEQ_MODEL to ONNX and dynamically int8-quantize
it for faster CPU inference in worker.py. Optional: the web (gunicorn) process
never imports `optimum`/`onnxruntime` — only this CLI command and
app/process.py's quantized-model branch do, and the latter only runs inside
worker.py, so these dependencies never load in the request-handling path.
"""
import os
import platform
import shutil
import tempfile

import click
from flask import current_app


def _pick_quantization_config():
    """Best dynamic-quantization preset for this CPU. No literal "detect my CPU"
    helper exists in Optimum despite the class being named AutoQuantizationConfig
    -- "Auto" there means "reasonable defaults for a given instruction set", so
    the instruction set itself is detected here, the same way deploy.py scans
    this box's hardware."""
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    if platform.machine() in ("aarch64", "arm64"):
        return AutoQuantizationConfig.arm64(is_static=False)

    flags = set()
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("flags") or line.startswith("Features"):
                    flags = set(line.split(":", 1)[1].split())
                    break
    except FileNotFoundError:
        pass

    if "avx512_vnni" in flags:
        return AutoQuantizationConfig.avx512_vnni(is_static=False)
    if "avx512f" in flags:
        return AutoQuantizationConfig.avx512(is_static=False)
    return AutoQuantizationConfig.avx2(is_static=False)


@click.command("quantize")
@click.option("--model", default=None,
              help="HF hub id or local path. Defaults to SEQ2SEQ_MODEL from app config.")
@click.option("--output", default=None,
              help="Output directory. Defaults to MODEL_QUANTIZED_PATH from app config.")
def quantize_command(model, output):
    """Export the normalization model to ONNX and dynamically quantize it to
    int8, so worker.py can load a smaller/faster model from disk instead of
    the original HuggingFace checkpoint. Re-run this any time SEQ2SEQ_MODEL
    changes; worker.py picks up the quantized model automatically on its next
    restart if the output directory exists."""
    from optimum.onnxruntime import ORTModelForSeq2SeqLM, ORTQuantizer
    from transformers import AutoTokenizer

    model_id = model or current_app.config["SEQ2SEQ_MODEL"]
    output_dir = output or current_app.config["MODEL_QUANTIZED_PATH"]

    click.echo(f"Exporting {model_id} to ONNX…")
    export_dir = tempfile.mkdtemp()
    try:
        ort_model = ORTModelForSeq2SeqLM.from_pretrained(model_id, export=True)
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        ort_model.save_pretrained(export_dir)
        tokenizer.save_pretrained(export_dir)

        onnx_files = [f for f in os.listdir(export_dir) if f.endswith(".onnx")]
        before_bytes = sum(os.path.getsize(os.path.join(export_dir, f)) for f in onnx_files)

        qconfig = _pick_quantization_config()
        click.echo(f"Quantizing {len(onnx_files)} ONNX component(s) (dynamic int8, "
                   f"{qconfig.__class__.__name__})…")
        os.makedirs(output_dir, exist_ok=True)
        for fname in onnx_files:
            quantizer = ORTQuantizer.from_pretrained(export_dir, file_name=fname)
            quantizer.quantize(save_dir=output_dir, quantization_config=qconfig, file_suffix=None)

        # Copy over everything the quantizer didn't write (tokenizer/config files).
        for fname in os.listdir(export_dir):
            if not fname.endswith(".onnx"):
                shutil.copy(os.path.join(export_dir, fname), os.path.join(output_dir, fname))
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    after_bytes = sum(
        os.path.getsize(os.path.join(output_dir, f))
        for f in os.listdir(output_dir) if f.endswith(".onnx")
    )
    click.echo(f"Done: {before_bytes / 1e6:.1f} MB -> {after_bytes / 1e6:.1f} MB, saved to {output_dir}")
    click.echo("Restart worker.py to pick up the quantized model.")
