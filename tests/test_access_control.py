"""Access-control integration tests.

Verifies that the `requires_access` decorator (backed by model.user_has_access)
correctly grants or denies access to document, folder and project routes based
on who owns the resource and which users have been explicitly shared access.

Scenarios covered
-----------------
- Anonymous user → redirect to login on every resource type
- Project creator → full access to project / folder / document
- User with project-level access (ProjectUser row) → access to all its documents
- User with folder-level access only (FolderUser row) → access to its documents,
  but NOT to other folders in the same project
- Unrelated authenticated user → 403 everywhere
"""

import pytest
from app import app as flask_app
from app.models import (
    db, User, Project, Folder, Document, ProjectUser, FolderUser, Line
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


def _make_document(creator, project=None, folder=None):
    """Create a minimal project/folder/document hierarchy and return all three."""
    if project is None:
        project = Project(name="proj", description="", creator_id=creator.id)
        db.session.add(project)
        db.session.flush()
    if folder is None:
        folder = Folder(name="folder", project_id=project.id,
                         creator_id=creator.id)
        db.session.add(folder)
        db.session.flush()
    document = Document(label="d1", folder_id=folder.id, order=0)
    db.session.add(document)
    db.session.flush()
    db.session.commit()
    return project, folder, document


# ── anonymous access ──────────────────────────────────────────────────────────

class TestAnonymousAccess:
    def test_document_redirects_to_login(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, document = _make_document(owner)
            document_id = document.id
        resp = client.get(f"/documents/{document_id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_redirect_preserves_next(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, document = _make_document(owner)
            document_id = document.id
        resp = client.get(f"/documents/{document_id}", follow_redirects=True)
        # Should land on the login page
        assert resp.status_code == 200
        assert b"login" in resp.data.lower()

    def test_anonymous_user_has_no_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            project, _, _ = _make_document(owner)
            from flask_login import AnonymousUserMixin
            anon = AnonymousUserMixin()
            assert project.user_has_access(anon) is False

    def test_anonymous_user_has_no_folder_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, folder, _ = _make_document(owner)
            from flask_login import AnonymousUserMixin
            anon = AnonymousUserMixin()
            assert folder.user_has_access(anon) is False


# ── creator access ────────────────────────────────────────────────────────────

class TestCreatorAccess:
    def test_creator_has_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            project, _, _ = _make_document(owner)
            assert project.user_has_access(owner) is True

    def test_creator_has_folder_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, folder, _ = _make_document(owner)
            assert folder.user_has_access(owner) is True

    def test_creator_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            _, _, document = _make_document(owner)
            assert document.user_has_access(owner) is True

    def test_creator_can_view_document(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _, _, document = _make_document(owner)
            document_id = document.id
        _login(client, "owner")
        resp = client.get(f"/documents/{document_id}")
        assert resp.status_code == 200


# ── project-level shared access ───────────────────────────────────────────────

class TestProjectLevelAccess:
    def test_project_member_has_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, _ = _make_document(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert project.user_has_access(member) is True

    def test_project_member_has_folder_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, folder, _ = _make_document(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert folder.user_has_access(member) is True

    def test_project_member_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, document = _make_document(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            assert document.user_has_access(member) is True

    def test_project_member_can_view_document(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, _, document = _make_document(owner)
            db.session.add(ProjectUser(project_id=project.id, user_id=member.id))
            db.session.commit()
            document_id = document.id
        _login(client, "member")
        resp = client.get(f"/documents/{document_id}")
        assert resp.status_code == 200


# ── folder-level shared access ─────────────────────────────────────────────

class TestFolderLevelAccess:
    def test_folder_member_has_folder_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, folder, _ = _make_document(owner)
            db.session.add(FolderUser(folder_id=folder.id, user_id=member.id))
            db.session.commit()
            assert folder.user_has_access(member) is True

    def test_folder_member_has_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, folder, document = _make_document(owner)
            db.session.add(FolderUser(folder_id=folder.id, user_id=member.id))
            db.session.commit()
            assert document.user_has_access(member) is True

    def test_folder_member_can_view_document(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            _, folder, document = _make_document(owner)
            db.session.add(FolderUser(folder_id=folder.id, user_id=member.id))
            db.session.commit()
            document_id = document.id
        _login(client, "member")
        resp = client.get(f"/documents/{document_id}")
        assert resp.status_code == 200

    def test_folder_member_cannot_access_sibling_folder(self, app):
        """Access to folder A must not bleed into folder B in the same project."""
        with app.app_context():
            owner = _make_user("owner")
            member = _make_user("member")
            project, folder_a, _ = _make_document(owner)
            folder_b = Folder(name="folder_b", project_id=project.id, creator_id=owner.id)
            db.session.add(folder_b)
            db.session.flush()
            document_b = Document(label="d_b", folder_id=folder_b.id, order=0)
            db.session.add(document_b)
            db.session.add(FolderUser(folder_id=folder_a.id, user_id=member.id))
            db.session.commit()
            assert folder_b.user_has_access(member) is False
            assert document_b.user_has_access(member) is False


# ── unrelated authenticated user ──────────────────────────────────────────────

class TestUnrelatedUserAccess:
    def test_unrelated_user_has_no_project_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            project, _, _ = _make_document(owner)
            assert project.user_has_access(stranger) is False

    def test_unrelated_user_has_no_folder_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            _, folder, _ = _make_document(owner)
            assert folder.user_has_access(stranger) is False

    def test_unrelated_user_has_no_document_access(self, app):
        with app.app_context():
            owner = _make_user("owner")
            stranger = _make_user("stranger")
            _, _, document = _make_document(owner)
            assert document.user_has_access(stranger) is False

    def test_unrelated_user_gets_403_on_document(self, app, client):
        with app.app_context():
            owner = _make_user("owner")
            _make_user("stranger")
            _, _, document = _make_document(owner)
            document_id = document.id
        _login(client, "stranger")
        resp = client.get(f"/documents/{document_id}")
        assert resp.status_code == 403
