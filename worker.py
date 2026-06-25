"""Background normalization worker.

Polls the `normalization_jobs` table (populated by app/bp_document.py's
document_create when a document is created with `normalize: true`), loads the
seq2seq model ONCE for the life of this process (unlike the old /api/normalize
route, which reloaded it on every request), and for each job processes its
chunks in order — committing each chunk's annotations to the database as soon
as that chunk comes back from the model, so already-normalized text becomes
visible in the editor before the rest of the document finishes.

Run as its own systemd unit (see deploy.py), separate from the gunicorn web
process:
    env/bin/python worker.py
"""
import sys
import time
from datetime import datetime, timezone

from app import app
from app.models import db, NormalizationJob, NormalizationJobChunk, Annotation, Document
from app.process import get_model_and_tokenizer, normalize_line
from app.annot_utils import align_one_chunk

POLL_INTERVAL_SECONDS = 2


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim_next_queued_job():
    """Atomically claim the oldest queued job under SQLite's single-writer
    model: the UPDATE only succeeds if the row is still 'queued' by the time
    it runs, so two workers racing on the same row is safe (one gets 0 rows
    affected and tries again)."""
    result = db.session.execute(
        db.text(
            "UPDATE normalization_jobs SET status='running', started_at=:now "
            "WHERE id = (SELECT id FROM normalization_jobs WHERE status='queued' ORDER BY id LIMIT 1) "
            "AND status='queued'"
        ),
        {"now": utcnow()},
    )
    db.session.commit()
    if result.rowcount == 0:
        return None
    return (
        NormalizationJob.query
        .filter_by(status="running")
        .order_by(NormalizationJob.started_at.desc())
        .first()
    )


def process_job(job: NormalizationJob, model, tokenizer) -> None:
    chunks = (
        NormalizationJobChunk.query
        .filter_by(job_id=job.id)
        .order_by(NormalizationJobChunk.order)
        .all()
    )
    # Slice annotation context from the real document text, not a
    # separator-joined reconstruction of the chunks — in punctuation mode a
    # chunk can span several original lines joined with a plain space, while
    # the document's real text has a newline there; see align_one_chunk's
    # docstring in app/annot_utils.py for why that matters.
    full_text = db.session.get(Document, job.document_id).full_text
    char_offset = 0
    for idx, chunk in enumerate(chunks):
        if chunk.reg is None:  # resume support: skip chunks already done by a prior (crashed) run
            reg = normalize_line(chunk.orig, model, tokenizer)
            chunk.reg = reg
            chunk.processed_at = utcnow()
            annots = align_one_chunk(chunk.orig, reg, full_text, char_offset)
            for a in annots:
                db.session.add(Annotation.from_dict(job.document_id, a))
            db.session.commit()  # this chunk's annotations are now visible immediately
        char_offset += len(chunk.orig)
        if idx < len(chunks) - 1:
            char_offset += len(job.separator)

    job.status = "done"
    job.finished_at = utcnow()
    db.session.commit()


def run():
    with app.app_context():
        print("worker: loading model…", file=sys.stderr, flush=True)
        model, tokenizer = get_model_and_tokenizer()
        print("worker: model loaded, polling for jobs", file=sys.stderr, flush=True)

        while True:
            job = claim_next_queued_job()
            if job is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            print(f"worker: processing job {job.id} (document {job.document_id})",
                  file=sys.stderr, flush=True)
            try:
                process_job(job, model, tokenizer)
                print(f"worker: job {job.id} done", file=sys.stderr, flush=True)
            except Exception as e:
                db.session.rollback()
                job = db.session.get(NormalizationJob, job.id)
                job.status = "failed"
                job.error = str(e)
                db.session.commit()
                print(f"worker: job {job.id} failed: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    run()
