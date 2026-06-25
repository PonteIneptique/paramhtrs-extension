"""End-to-end tests for the background normalization worker pipeline:

  document_create(normalize=true) -> NormalizationJob/NormalizationJobChunk rows
      -> worker.process_job() -> Annotations committed incrementally
      -> processing-status / annotations endpoints

These exercise the real Flask routes + SQLAlchemy models against an
in-memory SQLite database (no real ML model — normalize_line is monkeypatched).
"""
import pytest
from app import app as flask_app
from app.models import db, User, Project, Folder, Document, NormalizationJob, NormalizationJobChunk
from app.normalize_jobs import normalize_whitespace
import worker


@pytest.fixture()
def app():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def folder(app):
    user = User(username="owner", is_approved=True)
    user.set_password("pw")
    db.session.add(user)
    db.session.flush()
    project = Project(name="P", description="", creator_id=user.id)
    db.session.add(project)
    db.session.flush()
    f = Folder(name="F", description="", project_id=project.id, creator_id=user.id, language="lat")
    db.session.add(f)
    db.session.commit()
    return f


def _login(client):
    return client.post("/login", data={"username": "owner", "password": "pw"}, follow_redirects=True)


# ── document_create(normalize=true) ──────────────────────────────────────────

def test_normalize_true_queues_job_single_source(app, client, folder):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id,
        "label": "Doc1",
        "lines": [{"orig": "Hello wrld.", "alto_id": "l1"}, {"orig": "Secnd line."}],
        "normalize": True,
        "split_mode": "lines",
    })
    assert resp.status_code == 200
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)

    # Lines/full_text exist immediately — normalization hasn't run yet.
    assert doc.full_text == "Hello wrld.\nSecnd line."
    assert doc.annotations == []

    job = doc.active_job
    assert job is not None
    assert job.status == "queued"
    assert job.separator == "\n"
    assert [(c.part_index, c.orig) for c in job.chunks] == [(0, "Hello wrld."), (0, "Secnd line.")]


def test_normalize_true_queues_job_multi_source_punctuation(app, client, folder):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id,
        "label": "Doc2",
        "subparts": [
            {"id": "file1.xml", "lines": [{"orig": "Foo bar baz."}, {"orig": "Qux quux."}]},
            {"id": "file2.xml", "lines": [{"orig": "Another part line."}]},
        ],
        "normalize": True,
        "split_mode": "punctuation",
        "min_words": 1,
    })
    assert resp.status_code == 200
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)
    job = doc.active_job

    assert job.separator == " "
    # Chunks never merge lines from different parts (the punctuation-mode fix).
    assert [c.part_index for c in job.chunks] == [0, 0, 1]
    assert all("Another part line" not in c.orig for c in job.chunks if c.part_index == 0)


def test_normalize_false_paths_unaffected(app, client, folder):
    """The pre-existing synchronous chunks/full_reg import paths must still
    work exactly as before — no NormalizationJob created."""
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id,
        "label": "Doc3",
        "lines": [{"orig": "abc"}, {"orig": "def"}],
        "chunks": [{"orig": "abc", "reg": "ABC"}, {"orig": "def", "reg": "DEF"}],
        "separator": "\n",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)
    assert doc.normalized_text == "ABC\nDEF"
    assert doc.active_job is None


# ── worker.process_job ───────────────────────────────────────────────────────

def test_worker_processes_chunks_incrementally(app, client, folder, monkeypatch):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id,
        "label": "Doc4",
        "lines": [{"orig": "Hello wrld."}, {"orig": "Secnd line."}],
        "normalize": True,
        "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)
    job = doc.active_job

    fixes = {"Hello wrld.": "Hello world.", "Secnd line.": "Second line."}
    monkeypatch.setattr(worker, "normalize_line", lambda text, model, tok: fixes.get(text, text))

    worker.process_job(job, None, None)

    db.session.refresh(job)
    assert job.status == "done"
    assert job.processed_chunks == job.total_chunks == 2
    doc = db.session.get(Document, doc_id)
    assert doc.normalized_text == "Hello world.\nSecond line."


def test_worker_resumes_without_reprocessing_done_chunks(app, client, folder, monkeypatch):
    """A crashed/restarted worker must not re-call the model on chunks that
    already have `reg` set from a prior (partial) run."""
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc5",
        "lines": [{"orig": "abc"}, {"orig": "def"}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    job = db.session.get(Document, doc_id).active_job
    job.chunks[0].reg = "ABC"  # simulate a prior partial run
    db.session.commit()

    calls = []
    def counting_normalize(text, model, tok):
        calls.append(text)
        return text.upper()
    monkeypatch.setattr(worker, "normalize_line", counting_normalize)

    worker.process_job(job, None, None)

    assert calls == ["def"]
    db.session.refresh(job)
    assert job.status == "done"


def test_worker_marks_job_failed_on_exception(app, client, folder, monkeypatch):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc6",
        "lines": [{"orig": "abc"}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    job = db.session.get(Document, doc_id).active_job

    def failing_normalize(text, model, tok):
        raise RuntimeError("boom")
    monkeypatch.setattr(worker, "normalize_line", failing_normalize)

    with pytest.raises(RuntimeError):
        worker.process_job(job, None, None)
    db.session.rollback()
    job = db.session.get(NormalizationJob, job.id)
    job.status = "failed"
    job.error = "boom"
    db.session.commit()
    assert job.status == "failed"


def test_claim_next_queued_job_is_fifo_and_exclusive(app, folder):
    j1 = NormalizationJob(document_id=_make_document(folder).id, status="queued", separator="\n")
    j2 = NormalizationJob(document_id=_make_document(folder).id, status="queued", separator="\n")
    db.session.add_all([j1, j2])
    db.session.commit()

    claimed1 = worker.claim_next_queued_job()
    claimed2 = worker.claim_next_queued_job()
    claimed3 = worker.claim_next_queued_job()

    assert claimed1.id == j1.id
    assert claimed2.id == j2.id
    assert claimed3 is None
    assert claimed1.status == claimed2.status == "running"


def _make_document(folder):
    doc = Document(folder_id=folder.id, label="d", order=0, status="pending")
    db.session.add(doc)
    db.session.flush()
    return doc


# ── processing-status / annotations endpoints ────────────────────────────────

def test_processing_status_endpoints(app, client, folder, monkeypatch):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc7",
        "lines": [{"orig": "abc"}, {"orig": "def"}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])

    r = client.get(f"/api/documents/{doc_id}/processing-status")
    assert r.get_json() == {"processing": True, "status": "queued", "current": 0, "total": 2, "error": None}

    r = client.get(f"/api/folders/{folder.id}/processing-status")
    assert r.get_json() == {str(doc_id): {"status": "queued", "current": 0, "total": 2, "error": None}}

    job = db.session.get(Document, doc_id).active_job
    monkeypatch.setattr(worker, "normalize_line", lambda text, model, tok: text.upper())
    worker.process_job(job, None, None)

    r = client.get(f"/api/documents/{doc_id}/processing-status")
    body = r.get_json()
    assert body["processing"] is False
    assert body["status"] == "done"

    r = client.get(f"/api/folders/{folder.id}/processing-status")
    assert r.get_json() == {}

    r = client.get(f"/api/documents/{doc_id}/annotations")
    assert len(r.get_json()["annotations"]) == 2


# ── reprocess ─────────────────────────────────────────────────────────────────

def test_reprocess_queues_a_new_job_and_clears_old_annotations(app, client, folder, monkeypatch):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc8",
        "lines": [{"orig": "Hello wrld."}, {"orig": "Secnd line."}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    job = db.session.get(Document, doc_id).active_job
    monkeypatch.setattr(worker, "normalize_line", lambda text, model, tok: text.upper())
    worker.process_job(job, None, None)

    doc = db.session.get(Document, doc_id)
    first_run_count = len(doc.annotations)
    assert first_run_count > 0

    r = client.post(f"/api/documents/{doc_id}/reprocess", json={"split_mode": "lines"})
    assert r.status_code == 200

    doc = db.session.get(Document, doc_id)
    assert doc.annotations == []  # old annotations discarded immediately
    new_job = doc.active_job
    assert new_job.id != job.id
    assert new_job.status == "queued"

    worker.process_job(new_job, None, None)
    doc = db.session.get(Document, doc_id)
    # Same input/model behavior -> same number of annotations, not doubled.
    assert len(doc.annotations) == first_run_count


def test_reprocess_rejects_while_already_processing(app, client, folder):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc9",
        "lines": [{"orig": "abc"}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    # First job is still queued (worker hasn't run) — reprocess must be rejected.
    r = client.post(f"/api/documents/{doc_id}/reprocess", json={})
    assert r.status_code == 409


# ── offset correctness across a chunk that spans multiple original lines ────
# Regression for: punctuation-mode chunks joining several original Lines with
# a plain space, while Document.full_text has a real "\n" there. Position
# arithmetic was always correct; the bug was annotation exact/prefix/suffix
# text being sliced from the separator-joined reconstruction instead of the
# real document text, which only showed up when an edit landed exactly on
# that joint.

def test_normalize_whitespace_collapses_runs():
    assert normalize_whitespace("aa  bb") == "aa bb"
    assert normalize_whitespace("aa \n  bb") == "aa\nbb"
    assert normalize_whitespace("aa\n\n\nbb") == "aa\nbb"
    assert normalize_whitespace("aa\tbb") == "aa bb"


def test_double_space_in_a_line_no_longer_garbles_alignment(app, client, folder, monkeypatch):
    """Regression for the /document/22 bug: a line containing a double space
    (or other multi-char whitespace run) used to desync align_words' internal
    char positions from the char_offset bookkeeping in worker.py, garbling
    every annotation positioned after that run within the same chunk.

    document_create now normalises whitespace when storing Line.original_text
    (see normalize_jobs.normalize_whitespace), so the double space here is
    already collapsed by the time the chunk reaches the model/aligner."""
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc11",
        "lines": [{"orig": "aa  bb typo cc"}],
        "normalize": True, "split_mode": "lines",
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)
    assert doc.full_text == "aa bb typo cc"  # double space already collapsed

    job = doc.active_job
    monkeypatch.setattr(worker, "normalize_line",
                         lambda text, model, tok: text.replace("typo", "fix"))
    worker.process_job(job, None, None)

    doc = db.session.get(Document, doc_id)
    assert doc.normalized_text == "aa bb fix cc"


def test_worker_offsets_correct_when_model_merges_across_a_line_boundary(app, client, folder, monkeypatch):
    _login(client)
    resp = client.post("/documents/new", json={
        "folder_id": folder.id, "label": "Doc10",
        "subparts": [
            {"id": "p1.xml", "lines": [{"orig": "les ma"}, {"orig": "res auentures"}]},
        ],
        "normalize": True, "split_mode": "punctuation", "min_words": 1,
    })
    doc_id = int(resp.get_json()["redirect"].rstrip("/").split("/")[-1])
    doc = db.session.get(Document, doc_id)
    assert doc.full_text == "les ma\nres auentures"
    job = doc.active_job
    # Single punctuation-mode chunk spans both lines (no delimiter to split on):
    # its orig is "les ma res auentures" (space-joined) — exactly the case that
    # used to break exact/prefix/suffix slicing.
    assert len(job.chunks) == 1
    assert job.chunks[0].orig == "les ma res auentures"

    # Simulate the model merging "ma" + "res" across the line boundary, the
    # exact failure mode found with the real model.
    monkeypatch.setattr(worker, "normalize_line",
                         lambda text, model, tok: text.replace("ma res", "mares"))
    worker.process_job(job, None, None)

    doc = db.session.get(Document, doc_id)
    full_text = doc.full_text
    assert doc.annotations, "expected at least one annotation for the merge edit"
    for a in doc.annotations:
        sel = a["target"]["selector"]
        pos = next(s for s in sel if s["type"] == "TextPositionSelector")
        quo = next(s for s in sel if s["type"] == "TextQuoteSelector")
        assert full_text[pos["start"]:pos["end"]] == quo["exact"], (
            f"offset mismatch: full_text[{pos['start']}:{pos['end']}]="
            f"{full_text[pos['start']:pos['end']]!r} but exact={quo['exact']!r}"
        )
