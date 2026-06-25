"""`flask quantize` — Export SEQ2SEQ_MODEL to ONNX and dynamically int8-quantize
it for faster CPU inference in worker.py.
"""
import os
import platform
import shutil
import tempfile

import click
from flask import current_app


def _pick_quantization_config():
    """Best dynamic-quantization preset for this CPU. Maps directly 
    to valid ONNX Runtime IntegerOps architectures behind the scenes.
    """
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
@click.option("--quantize", default=False, is_flag=True,
              help="Apply dynamic quantization optimized for ByT5 CPU execution.")
def quantize_command(model, output, quantize):
    """Export the model to ONNX using valid dynamic configurations.
    This safely compresses model weights without triggering ORT type mismatches.
    """
    from optimum.onnxruntime import ORTModelForSeq2SeqLM, ORTQuantizer
    from transformers import AutoTokenizer

    model_id = model or current_app.config["SEQ2SEQ_MODEL"]
    output_dir = output or current_app.config["MODEL_QUANTIZED_PATH"]

    click.echo(f"Exporting {model_id} to vanilla ONNX layout…")
    export_dir = tempfile.mkdtemp()
    try:
        # Step 1: Export clean unquantized standard ONNX graph
        ort_model = ORTModelForSeq2SeqLM.from_pretrained(model_id, export=True)
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        
        ort_model.save_pretrained(export_dir)
        tokenizer.save_pretrained(export_dir)

        onnx_files = [f for f in os.listdir(export_dir) if f.endswith(".onnx")]
        before_bytes = sum(os.path.getsize(os.path.join(export_dir, f)) for f in onnx_files)

        os.makedirs(output_dir, exist_ok=True)

        if quantize:
            # Step 2: Dynamically load hardware-matched config
            qconfig = _pick_quantization_config()
            click.echo(f"Quantizing ONNX components via AutoQuantizationConfig ({qconfig.__class__.__name__})...")
            
            # Step 3: Quantize individual ONNX sub-graphs
            for fname in onnx_files:
                quantizer = ORTQuantizer.from_pretrained(export_dir, file_name=fname)
                quantizer.quantize(
                    save_dir=output_dir,
                    quantization_config=qconfig,
                    file_suffix=None
                )
        else:
            for fname in onnx_files:
                shutil.copy(os.path.join(export_dir, fname), os.path.join(output_dir, fname))

        # Step 4: Copy configs and tokenizer assets
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
    click.echo("Restart worker.py to spin up your dynamic ONNX execution backend.")