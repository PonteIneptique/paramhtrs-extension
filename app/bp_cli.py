"""Flask CLI commands for offline text processing.

Usage (from project root):
  env/bin/flask align --orig-file orig.txt
  env/bin/flask align --orig-file orig.txt --model ./model
  env/bin/flask align --orig "some text" --reg "regularized text"
  env/bin/flask align --orig-file orig.txt --chunks-only
"""
import sys
import click
from flask.cli import AppGroup

from .bp_norm import _split_on_punct, _enforce_max_bytes
from .alignment import align_words

cli_group = AppGroup("align", help="Chunk & align original vs regularized text.")

_LABEL = {"n": "match", "s": "sub  ", "i": "ins  ", "d": "del  "}


# ── helpers ───────────────────────────────────────────────────────────────────

def _chunk_text(text: str, delimiters: list[str], min_words: int, max_bytes: int) -> list[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    full_text = " ".join(lines)
    chunks = _split_on_punct(full_text, delimiters, min_words)
    return _enforce_max_bytes(chunks, max_bytes)


def _print_alignments(alignments: list, show_nulls: bool) -> None:
    prev_chunk = None
    for a in alignments:
        chunk = getattr(a, "_chunk", None)
        if chunk != prev_chunk:
            click.echo(f"\n── chunk {chunk} {'─' * 50}")
            prev_chunk = chunk
        if not show_nulls and a.code == "n":
            continue
        label = _LABEL.get(a.code, a.code)
        click.echo(f"  {label}\t{a.source!r:<40} → {a.target!r}")


# ── command ───────────────────────────────────────────────────────────────────

@cli_group.command("run")
@click.option("--orig",      default=None, help="Original text as a string.")
@click.option("--orig-file", default=None, type=click.Path(exists=True),
              help="File containing the original text.")
@click.option("--reg",       default=None, help="Pre-computed regularized text (skips the model).")
@click.option("--reg-file",  default=None, type=click.Path(exists=True),
              help="File with pre-computed regularized text.")
@click.option("--model",     default=None,
              help="HF hub id or local path. Defaults to SEQ2SEQ_MODEL from app config.")
@click.option("--delimiters", default="¶;.", show_default=True,
              help="Delimiter characters for punctuation-mode splitting.")
@click.option("--min-words", default=100, show_default=True, type=int,
              help="Minimum words per chunk.")
@click.option("--max-bytes", default=512, show_default=True, type=int,
              help="Maximum bytes per chunk.")
@click.option("--hide-nulls", is_flag=True, help="Suppress match (null) alignments.")
@click.option("--chunks-only", is_flag=True, help="Print chunks only, skip alignment.")
def align_run(orig, orig_file, reg, reg_file, model, delimiters,
              min_words, max_bytes, hide_nulls, chunks_only):
    """Chunk a text and align it against its normalized form."""
    from flask import current_app

    # ── read original ─────────────────────────────────────────────────────────
    if orig:
        orig_text = orig
    elif orig_file:
        with open(orig_file, encoding="utf-8") as f:
            orig_text = f.read()
    elif not sys.stdin.isatty():
        orig_text = sys.stdin.read()
    else:
        raise click.UsageError("Provide original text via --orig, --orig-file, or stdin.")

    delim_list = list(delimiters)
    orig_chunks = _chunk_text(orig_text, delim_list, min_words, max_bytes)

    if chunks_only:
        for i, c in enumerate(orig_chunks):
            click.echo(f"── chunk {i} ({len(c.encode())} bytes, {len(c.split())} words) ──")
            click.echo(c)
            click.echo()
        return

    # ── obtain regularized chunks ─────────────────────────────────────────────
    if reg or reg_file:
        reg_text = reg if reg else open(reg_file, encoding="utf-8").read()
        reg_chunks = _chunk_text(reg_text, delim_list, min_words, max_bytes)
    else:
        from .process import normalize_line, get_model_and_tokenizer
        model_path = model or current_app.config["SEQ2SEQ_MODEL"]
        click.echo(f"Loading model: {model_path} …", err=True)
        m, tok = get_model_and_tokenizer() if model is None else _load_model(model_path)
        total = len(orig_chunks)
        reg_chunks = []
        for i, chunk in enumerate(orig_chunks, 1):
            click.echo(f"  normalizing chunk {i}/{total} ({len(chunk.encode())} bytes) …", err=True)
            reg_chunks.append(normalize_line(chunk, m, tok))
            print(f"---> {reg_chunks[-1]}")

    # ── align ─────────────────────────────────────────────────────────────────
    if len(orig_chunks) != len(reg_chunks):
        raise click.ClickException(
            f"Chunk count mismatch: {len(orig_chunks)} orig vs {len(reg_chunks)} reg. "
            "Make sure both sides use the same chunking settings."
        )

    all_alignments = []
    for i, (o, r) in enumerate(zip(orig_chunks, reg_chunks)):
        for a in align_words(o, r):
            a._chunk = i
            all_alignments.append(a)

    _print_alignments(all_alignments, show_nulls=not hide_nulls)


def _load_model(model_path: str):
    """Load model + tokenizer from an arbitrary path (bypasses current_app.config)."""
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    return (
        AutoModelForSeq2SeqLM.from_pretrained(model_path),
        AutoTokenizer.from_pretrained(model_path),
    )
