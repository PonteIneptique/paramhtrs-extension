"""`flask quantize` — Export SEQ2SEQ_MODEL to ONNX and dynamically int8-quantize
it for faster CPU inference in worker.py.

The export itself lives in penelopy (penelopy.models.quantize, extracted from
this module); what stays here is the click/Flask-config wrapper.
"""
import click
from flask import current_app

from penelopy.models.quantize import quantize_model


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
    model_id = model or current_app.config["SEQ2SEQ_MODEL"]
    output_dir = output or current_app.config["MODEL_QUANTIZED_PATH"]

    click.echo(f"Exporting {model_id} to vanilla ONNX layout…")
    if quantize:
        click.echo("Quantizing ONNX components via a CPU-matched AutoQuantizationConfig…")
    before_mb, after_mb = quantize_model(model_id, output_dir, quantize)
    click.echo(f"Done: {before_mb:.1f} MB -> {after_mb:.1f} MB, saved to {output_dir}")
    click.echo("Restart worker.py to spin up your dynamic ONNX execution backend.")
