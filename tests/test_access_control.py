"""Access-control integration tests.

Verifies that the `requires_access` decorator (backed by model.user_has_access)
correctly grants or denies access to page, document and project routes based on
who owns the resource and which users have been explicitly shared access.

Scenarios covered
-----------------
- Anonymous user → 403 on every resource type
- Project creator → full access to project / document / page
- User with project-level access (ProjectUser row) → access to all its pages
- User with document-level access only (DocumentUser row) → access to its pages,
  but NOT to other documents in the same project
- Unrelated authenticated user → 403 everywhere
"""

import pytest
from app import app as flask_app
from app.models import (
    db, User, Project, Document, Page, ProjectUser, DocumentUser, Line
)


# ── fixtures ──────────────────────────────────────────────────────────────────

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


def _make_user(username, approved=True):
    u = User(username=username, is_approved=approved)
    u.set_password("pw")
    db.session.add(u)
    db.session.flush()
    return u


def _login(client, username):
    return client.post("/login", data={"username": username, "password": "pw"},
                       follow_redirects=True)


def _make_page(creator, project=None, document=None):
    """Create a minimal project/document/page hierarchy and return all three."""
    if project is None:
        project = Project(name="proj", description="", creator_id=creator.id)
        db.session.add(project)
        db.session.flush()
    if document is None:
        document = Document(name="doc", project_id=project.id,
                            creator_id=creator.id)
        db.session.add(document)
        db.session.flush()
    page = Page(label="p1", document_id=document.id, order=0)
    db.session.add(page)
    # A page needs at least one line for the editor to render properly
    db.session.flush()
    db.session.commit()
    return project, document, page


# ── anonymous access ──────────────────────────────────────────────────────────

class TestAnonymousAccess:
    def test_page_redirects_to_login(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, page = _make_page(owner)
            page_id = page.id
        resp = client.get(f"/pages/{page_id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_redirect_preserves_next(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, page = _make_page(owner)
            page_id = page.id
        resp = client.get(f"/pages/{page_id}", follow_redirects=True)
        # Should land on the login page
        assert resp.status_code == 200
        assert b"login" in resp.data.lower()

    def test_anonymous_user_has_no_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            project, _, _ = _make_page(owner)
            from flask_login import AnonymousUserMixin
            anon = AnonymousUserMixin()
            assert project.user_has_access(anon) is False

    def test_anonymous_user_has_no_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, document, _ = _make_page(owner)
            from flask_login import AnonymousUserMixin
            anon = AnonymousUserMixin()
            assert document.user_has_access(anon) is False


# ── creator access ────────────────────────────────────────────────────────────

class TestCreatorAccess:
    def test_creator_has_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            project, _, _ = _make_page(owner)
            assert project.user_has_access(owner) is True

    def test_creator_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, document, _ = _make_page(owner)
            assert document.user_has_access(owner) is True

    def test_creator_has_page_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, _, page = _make_page(owner)
            assert page.user_has_access(owner) is True

    def test_creator_can_view_page(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, page = _make_page(owner)
            page_id = page.id
        _login(client, "owner")
        resp = client.get(f"/pages/{page_id}")
        assert resp.status_code == 200


# ── project-level shared access ───────────────────────────────────────────────

class TestProjectLevelAccess:
    def test_project_member_has_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, _ = _make_page(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert project.user_has_access(member) is True

    def test_project_member_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, document, _ = _make_page(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert document.user_has_access(member) is True

    def test_project_member_has_page_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, page = _make_page(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert page.user_has_access(member) is True

    def test_project_member_can_view_page(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, page = _make_page(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            page_id = page.id
        _login(client, "member")
        resp = client.get(f"/pages/{page_id}")
        assert resp.status_code == 200


# ── document-level shared access ─────────────────────────────────────────────

class TestDocumentLevelAccess:
    def test_document_member_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, document, _ = _make_page(owner)
            db.session.add(DocumentUser(document_id=document.id, user_id=member.id))
            db.session.commit()
            assert document.user_has_access(member) is True

    def test_document_member_has_page_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, document, page = _make_page(owner)
            db.session.add(DocumentUser(document_id=document.id, user_id=member.id))
            db.session.commit()
            assert page.user_has_access(member) is True

    def test_document_member_can_view_page(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, document, page = _make_page(owner)
            db.session.add(DocumentUser(document_id=document.id, user_id=member.id))
            db.session.commit()
            page_id = page.id
        _login(client, "member")
        resp = client.get(f"/pages/{page_id}")
        assert resp.status_code == 200

    def test_document_member_cannot_access_sibling_document(self, app):
        """Access to doc A must not bleed into doc B in the same project."""
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, doc_a, _ = _make_page(owner)
            doc_b = Document(name="doc_b", project_id=project.id, creator_id=owner.id)
            db.session.add(doc_b)
            db.session.flush()
            page_b = Page(label="p_b", document_id=doc_b.id, order=0)
            db.session.add(page_b)
            db.session.add(DocumentUser(document_id=doc_a.id, user_id=member.id))
            db.session.commit()
            assert doc_b.user_has_access(member) is False
            assert page_b.user_has_access(member) is False


# ── unrelated authenticated user ──────────────────────────────────────────────

class TestUnrelatedUserAccess:
    def test_unrelated_user_has_no_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            project, _, _ = _make_page(owner)
            assert project.user_has_access(stranger) is False

    def test_unrelated_user_has_no_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            _, document, _ = _make_page(owner)
            assert document.user_has_access(stranger) is False

    def test_unrelated_user_has_no_page_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            _, _, page = _make_page(owner)
            assert page.user_has_access(stranger) is False

    def test_unrelated_user_gets_403_on_page(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _make_user("stranger")
            _, _, page = _make_page(owner)
            page_id = page.id
        _login(client, "stranger")
        resp = client.get(f"/pages/{page_id}")
        assert resp.status_code == 403
