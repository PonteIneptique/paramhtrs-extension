"""Tests for annotation re-offsetting when a line is deleted.

Annotation offsets are absolute character positions into Document.full_text,
which is derived live from the lines table. Deleting a line therefore has to
shift every annotation after it, or the whole document desyncs at once: editor
highlighting, normalized_text and TEI export all slice full_text by those
offsets.

The invariant under test, asserted after every deletion:
    document.full_text[a.target_start:a.target_end] == a.target_exact
"""

import pytest

from app import app as flask_app
from app.annot_utils import remap_offsets_after_deletion
from app.models import db, User, Project, Folder, Document, Part, Line, Annotation


# ── fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture()
def app():
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret",
        LOGIN_DISABLED=False,
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_user(username="owner"):
    u = User(username=username, is_approved=True)
    u.set_password("pw")
    db.session.add(u)
    db.session.flush()
    return u


def _login(client, username="owner"):
    return client.post("/login", data={"username": username, "password": "pw"},
                       follow_redirects=True)


def _make_document(owner, parts_lines):
    """Build a Document from `parts_lines`, a list of parts, each a list of
    line texts. Returns the Document."""
    project = Project(name="proj", description="", creator_id=owner.id)
    db.session.add(project)
    db.session.flush()
    folder = Folder(name="folder", project_id=project.id, creator_id=owner.id)
    db.session.add(folder)
    db.session.flush()
    document = Document(label="d1", folder_id=folder.id, order=0)
    db.session.add(document)
    db.session.flush()
    for p_order, texts in enumerate(parts_lines):
        part = Part(document_id=document.id, order=p_order)
        db.session.add(part)
        db.session.flush()
        for l_order, text in enumerate(texts):
            db.session.add(Line(part_id=part.id, order=l_order, original_text=text))
    db.session.commit()
    return document


def _annotate(document, start, end, value="X"):
    """Add an annotation over full_text[start:end], with a correct quote cache."""
    text = document.full_text
    annot = Annotation(
        id=f"a{start}-{end}",
        document_id=document.id,
        body_value=value,
        body_purpose="normalizing",
        target_start=start,
        target_end=end,
        target_exact=text[start:end],
        target_prefix=text[max(0, start - 10):start],
        target_suffix=text[end:end + 10],
    )
    db.session.add(annot)
    db.session.commit()
    return annot


def _delete_line(client, line_id):
    resp = client.post(f"/api/lines/{line_id}/delete")
    assert resp.status_code == 200, resp.data
    return resp.get_json()


def _assert_invariant(document):
    """Every surviving annotation must still slice the text it claims."""
    text = document.full_text
    for a in Annotation.query.filter_by(document_id=document.id).all():
        assert text[a.target_start:a.target_end] == a.target_exact, (
            f"annotation {a.id} points at "
            f"{text[a.target_start:a.target_end]!r}, cached {a.target_exact!r}"
        )
        assert a.target_prefix == text[max(0, a.target_start - 10):a.target_start]
        assert a.target_suffix == text[a.target_end:a.target_end + 10]


def _by_id(document):
    return {a.id: a for a in Annotation.query.filter_by(document_id=document.id).all()}


# ── the pure remapping helper ─────────────────────────────────────────────────
#
# Deleting a line removes the range [d0, d1). Below, the cut is always [10, 20).

CUT = (10, 20)


class TestRemapOffsets:
    def test_entirely_before_is_untouched(self):
        assert remap_offsets_after_deletion(2, 8, *CUT) == (2, 8)

    def test_ending_exactly_at_cut_start_is_untouched(self):
        assert remap_offsets_after_deletion(4, 10, *CUT) == (4, 10)

    def test_entirely_after_shifts_by_deleted_length(self):
        assert remap_offsets_after_deletion(30, 35, *CUT) == (20, 25)

    def test_starting_exactly_at_cut_end_shifts(self):
        assert remap_offsets_after_deletion(20, 24, *CUT) == (10, 14)

    def test_entirely_inside_is_dropped(self):
        assert remap_offsets_after_deletion(12, 18, *CUT) is None

    def test_exactly_covering_the_cut_is_dropped(self):
        assert remap_offsets_after_deletion(10, 20, *CUT) is None

    def test_starts_before_ends_inside_clamps_to_cut_start(self):
        assert remap_offsets_after_deletion(5, 15, *CUT) == (5, 10)

    def test_starts_inside_ends_after_clamps_start(self):
        assert remap_offsets_after_deletion(15, 30, *CUT) == (10, 20)

    def test_spanning_the_whole_cut_keeps_start_shifts_end(self):
        assert remap_offsets_after_deletion(5, 30, *CUT) == (5, 20)

    def test_insertion_before_is_untouched(self):
        assert remap_offsets_after_deletion(5, 5, *CUT) == (5, 5)

    def test_insertion_at_cut_boundaries_survives(self):
        assert remap_offsets_after_deletion(10, 10, *CUT) == (10, 10)
        assert remap_offsets_after_deletion(20, 20, *CUT) == (10, 10)

    def test_insertion_strictly_inside_is_dropped(self):
        assert remap_offsets_after_deletion(15, 15, *CUT) is None

    def test_insertion_after_shifts(self):
        assert remap_offsets_after_deletion(30, 30, *CUT) == (20, 20)


# ── endpoint behaviour ────────────────────────────────────────────────────────

class TestLineDeleteEndpoint:
    def test_middle_line_shifts_later_annotations(self, app, client):
        """The reported bug: annotations after the deleted line kept stale offsets."""
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[1].id
            # "alpha\nbravo\ncharlie" — one annotation per line
            _annotate(document, 0, 5, "A")       # alpha
            _annotate(document, 6, 11, "B")      # bravo (deleted)
            _annotate(document, 12, 19, "C")     # charlie
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            assert document.full_text == "alpha\ncharlie"
            annots = _by_id(document)
            assert "a6-11" not in annots                      # on the deleted line
            assert (annots["a0-5"].target_start, annots["a0-5"].target_end) == (0, 5)
            assert (annots["a12-19"].target_start, annots["a12-19"].target_end) == (6, 13)
            _assert_invariant(document)

    def test_response_carries_new_full_text(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            line_id = document.lines[1].id
        _login(client)
        with app.app_context():
            data = _delete_line(client, line_id)
            assert data["full_text"] == "alpha\ncharlie"

    def test_first_line(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[0].id
            _annotate(document, 0, 5, "A")
            _annotate(document, 6, 11, "B")
            _annotate(document, 12, 19, "C")
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            assert document.full_text == "bravo\ncharlie"
            annots = _by_id(document)
            assert "a0-5" not in annots
            assert (annots["a6-11"].target_start, annots["a6-11"].target_end) == (0, 5)
            assert (annots["a12-19"].target_start, annots["a12-19"].target_end) == (6, 13)
            _assert_invariant(document)

    def test_last_line_removes_preceding_newline(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[2].id
            _annotate(document, 0, 5, "A")
            _annotate(document, 6, 11, "B")
            _annotate(document, 12, 19, "C")
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            assert document.full_text == "alpha\nbravo"
            annots = _by_id(document)
            assert "a12-19" not in annots
            assert (annots["a6-11"].target_start, annots["a6-11"].target_end) == (6, 11)
            _assert_invariant(document)

    def test_only_line_of_document(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha"]])
            doc_id, line_id = document.id, document.lines[0].id
            _annotate(document, 0, 5, "A")
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            assert document.full_text == ""
            assert Annotation.query.filter_by(document_id=doc_id).count() == 0

    def test_deletion_in_first_part_shifts_second_part(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo"], ["charlie", "delta"]])
            # "alpha\nbravo\ncharlie\ndelta"
            doc_id, line_id = document.id, document.lines[0].id
            _annotate(document, 12, 19, "C")     # charlie, in part 2
            _annotate(document, 20, 25, "D")     # delta, in part 2
            second_part_id = document.parts[1].id
        _login(client)
        with app.app_context():
            data = _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            assert document.full_text == "bravo\ncharlie\ndelta"
            annots = _by_id(document)
            assert (annots["a12-19"].target_start, annots["a12-19"].target_end) == (6, 13)
            assert (annots["a20-25"].target_start, annots["a20-25"].target_end) == (14, 19)
            _assert_invariant(document)
            # part boundaries move too, and the response reports the new ones
            offsets = {o["part_id"]: o["start"] for o in document.part_offsets}
            assert offsets[second_part_id] == 6
            assert data["part_offsets"] == document.part_offsets

    def test_annotation_spanning_the_line_boundary_is_clamped(self, app, client):
        """The aligner deliberately produces annotations that cross a newline."""
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[1].id
            _annotate(document, 3, 8, "span")    # "ha\nbr" — crosses into bravo
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            annots = _by_id(document)
            a = annots["a3-8"]
            # The "br" is gone; "ha" and the newline that preceded bravo survive.
            assert (a.target_start, a.target_end) == (3, 6)
            assert a.target_exact == "ha\n"      # quote cache refreshed
            _assert_invariant(document)

    def test_annotation_before_the_line_is_untouched(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[2].id
            _annotate(document, 0, 5, "A")
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            a = _by_id(document)["a0-5"]
            assert (a.target_start, a.target_end, a.target_exact) == (0, 5, "alpha")

    def test_insertion_on_the_deleted_line_is_removed(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[1].id
            _annotate(document, 8, 8, "ins")     # inside bravo
            _annotate(document, 14, 14, "keep")  # inside charlie
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
            document = db.session.get(Document, doc_id)
            annots = _by_id(document)
            assert "a8-8" not in annots
            assert (annots["a14-14"].target_start, annots["a14-14"].target_end) == (8, 8)

    def test_line_row_is_gone_and_state_is_consistent_after_commit(self, app, client):
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo", "charlie"]])
            doc_id, line_id = document.id, document.lines[1].id
            _annotate(document, 0, 5, "A")
            _annotate(document, 6, 11, "B")
            _annotate(document, 12, 19, "C")
        _login(client)
        with app.app_context():
            _delete_line(client, line_id)
        # Fresh session: nothing depends on in-request ORM state
        with app.app_context():
            document = db.session.get(Document, doc_id)
            assert db.session.get(Line, line_id) is None
            assert len(document.lines) == 2
            assert Annotation.query.filter_by(document_id=doc_id).count() == 2
            _assert_invariant(document)

    def test_get_does_not_delete(self, app, client):
        """The route mutates annotations now; keep it off GET. (The blueprint's
        catch-all static route swallows the unmatched GET, so this 404s rather
        than 405s — what matters is that nothing was deleted.)"""
        with app.app_context():
            owner = _make_user()
            document = _make_document(owner, [["alpha", "bravo"]])
            doc_id, line_id = document.id, document.lines[0].id
        _login(client)
        assert client.get(f"/api/lines/{line_id}/delete").status_code in (404, 405)
        with app.app_context():
            assert db.session.get(Line, line_id) is not None
            assert db.session.get(Document, doc_id).full_text == "alpha\nbravo"
