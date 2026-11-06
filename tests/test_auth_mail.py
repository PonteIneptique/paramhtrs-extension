"""Optional mail: registration notice, approval mail, password reset, default certainty."""
import pytest
from app import app as flask_app
from app.mailer import mail, make_reset_token
from app.models import db, User, get_default_cert, AppSetting


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True, SECRET_KEY="test-secret", MAIL_SERVER=None,
                            MAIL_DEFAULT_SENDER="app@x.org", ADMIN_EMAIL=None)
    flask_app.extensions['mail'].suppress = True   # read once at init_app, so set it on the state
    with flask_app.app_context():
        db.create_all()
        admin = User(username="root", email="root@x.org", is_admin=True, is_approved=True)
        admin.set_password("pw")
        db.session.add(admin)
        db.session.commit()
        yield flask_app.test_client()
        db.session.remove()
        db.drop_all()


def _register(client, **kw):
    data = {"username": "bob", "password": "pw", "email": "bob@x.org", **kw}
    return client.post("/register", data=data)


def test_mail_off_registration_needs_no_email_and_sends_nothing(client):
    with mail.record_messages() as out:
        r = _register(client, email="")
        assert r.status_code == 302
    assert out == []
    assert User.query.filter_by(username="bob").one().email is None


def test_mail_off_forgot_password_unavailable(client):
    assert client.get("/forgot_password").status_code == 302


def test_mail_on_registration_requires_email_and_notifies_admin(client):
    flask_app.config["MAIL_SERVER"] = "smtp.example"
    assert User.query.filter_by(username="bob").first() is None
    _register(client, email="")
    assert User.query.filter_by(username="bob").first() is None
    with mail.record_messages() as out:
        _register(client)
        import time; time.sleep(0.2)
    assert User.query.filter_by(username="bob").one()
    assert [m.recipients for m in out] == [["root@x.org"]]
    assert "bob" in out[0].body


def test_reset_flow_is_single_use_and_does_not_leak(client):
    flask_app.config["MAIL_SERVER"] = "smtp.example"
    bob = User(username="bob", email="bob@x.org", is_approved=True)
    bob.set_password("old")
    db.session.add(bob); db.session.commit()

    with mail.record_messages() as out:
        client.post("/forgot_password", data={"email": "nobody@x.org"})
        client.post("/forgot_password", data={"email": "bob@x.org"})
        import time; time.sleep(0.2)
    assert [m.recipients for m in out] == [["bob@x.org"]]

    token = make_reset_token(bob)
    client.post(f"/reset_password/{token}", data={"new_password": "new", "confirm_password": "new"})
    assert User.query.filter_by(username="bob").one().check_password("new")
    # the same link no longer works
    assert client.get(f"/reset_password/{token}").status_code == 302
    assert client.get("/reset_password/garbage").status_code == 302


def test_default_certainty_setting(client):
    assert get_default_cert() == "ocr_fix"
    AppSetting.set("default_cert", "informed"); db.session.commit()
    assert get_default_cert() == "informed"
    AppSetting.set("default_cert", "bogus"); db.session.commit()
    assert get_default_cert() == "ocr_fix"


def test_document_default_cert_overrides_instance_default(client):
    from app.models import Project, Folder, Document
    owner = User.query.filter_by(username="root").one()
    proj = Project(name="p", description="", creator_id=owner.id); db.session.add(proj); db.session.flush()
    folder = Folder(name="f", project_id=proj.id, creator_id=owner.id); db.session.add(folder); db.session.flush()
    doc = Document(label="d", folder_id=folder.id, order=0); db.session.add(doc); db.session.commit()

    AppSetting.set("default_cert", "ambiguous"); db.session.commit()
    assert doc.effective_default_cert == "ambiguous"        # falls back to the instance default

    client.post("/login", data={"username": "root", "password": "pw"})
    assert client.post(f"/api/documents/{doc.id}/default_cert", json={"default_cert": "bogus"}).status_code == 400
    assert client.post(f"/api/documents/{doc.id}/default_cert", json={"default_cert": "informed"}).status_code == 200
    db.session.refresh(doc)
    assert doc.effective_default_cert == "informed"
    assert '"informed"' in client.get(f"/documents/{doc.id}").get_data(as_text=True)


# ── Password change lives on the profile page ────────────────────────────────

def _login(client, user="root", pw="pw"):
    client.post("/login", data={"username": user, "password": pw})


def test_profile_page_has_the_password_form(client):
    _login(client)
    html = client.get("/profile").get_data(as_text=True)
    assert 'action="/change_password"' in html
    assert 'name="old_password"' in html and 'name="confirm_password"' in html


def test_change_password_from_profile(client):
    _login(client)
    r = client.post("/change_password", data={"old_password": "pw", "new_password": "n3w",
                                              "confirm_password": "n3w"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/profile")
    assert User.query.filter_by(username="root").one().check_password("n3w")


@pytest.mark.parametrize("data", [
    {"old_password": "WRONG", "new_password": "n3w", "confirm_password": "n3w"},
    {"old_password": "pw", "new_password": "n3w", "confirm_password": "different"},
    {"old_password": "pw", "new_password": "", "confirm_password": ""},
])
def test_change_password_rejects_bad_input(client, data):
    _login(client)
    client.post("/change_password", data=data)
    assert User.query.filter_by(username="root").one().check_password("pw")


def test_change_password_get_redirects_to_profile(client):
    _login(client)
    r = client.get("/change_password")
    assert r.status_code == 302 and r.headers["Location"].endswith("/profile")


def test_sidebar_no_longer_links_change_password(client):
    _login(client)
    assert "/change_password" not in client.get("/profile").get_data(as_text=True).split('<div class="container')[0]


# ── Username change on the profile page ──────────────────────────────────────

def _profile_post(client, **over):
    data = {"username": "root", "first_name": "", "last_name": "", "email": "root@x.org",
            "nickname": "", "orcid": "", "institution": "", **over}
    return client.post("/profile", data=data)


def test_username_can_be_changed_and_used_to_log_in(client):
    _login(client)
    _profile_post(client, username="newroot")
    assert User.query.filter_by(username="newroot").one().is_admin
    client.get("/logout")
    r = client.post("/login", data={"username": "newroot", "password": "pw"})
    assert r.status_code == 302


def test_username_must_be_unique_and_non_empty(client):
    other = User(username="bob", is_approved=True); other.set_password("x")
    db.session.add(other); db.session.commit()
    _login(client)
    _profile_post(client, username="bob")
    _profile_post(client, username="   ")
    assert User.query.filter_by(username="root").count() == 1


def test_email_is_editable_on_profile(client):
    _login(client)
    _profile_post(client, email="Back@X.org")
    assert User.query.filter_by(username="root").one().email == "back@x.org"


def test_admin_page_lists_users_with_email(client):
    _login(client)
    html = client.get("/admin").get_data(as_text=True)
    assert "root@x.org" in html and 'name="new_password"' in html


# ── Missing email on a mail-enabled instance: enter it, then confirm it ──────

@pytest.fixture()
def mail_on(client):
    flask_app.config["MAIL_SERVER"] = "smtp.example.org"
    yield client
    flask_app.config["MAIL_SERVER"] = None


def _html_get(client, url):
    return client.get(url, headers={"Accept": "text/html"})


def _no_email_user():
    u = User(username="alice", is_approved=True); u.set_password("pw")
    db.session.add(u); db.session.commit()


def test_user_without_email_is_sent_to_complete_email(mail_on):
    _no_email_user(); _login(mail_on, "alice")
    r = _html_get(mail_on, "/profile")
    assert r.status_code == 302 and r.headers["Location"].endswith("/complete_email")
    # the page itself, logout and fetch()-style calls are not redirected
    assert _html_get(mail_on, "/complete_email").status_code == 200
    assert mail_on.get("/profile", headers={"Accept": "*/*"}).status_code == 200


def test_no_redirect_when_mail_is_off_or_email_present(client):
    _no_email_user(); _login(client, "alice")
    assert _html_get(client, "/profile").status_code == 200          # mail off
    flask_app.config["MAIL_SERVER"] = "smtp.example.org"
    try:
        _login(client, "root")                                        # root has an email
        client.get("/logout"); _login(client, "root")
        assert _html_get(client, "/profile").status_code == 200
    finally:
        flask_app.config["MAIL_SERVER"] = None


def test_email_is_saved_only_after_the_link_is_followed(mail_on):
    _no_email_user(); _login(mail_on, "alice")
    with mail.record_messages() as out:
        mail_on.post("/complete_email", data={"email": "Alice@X.org"})
        import time; time.sleep(0.2)
    assert User.query.filter_by(username="alice").one().email is None     # not stored yet
    assert out and out[0].recipients == ["alice@x.org"]
    link = [w for w in out[0].body.split() if "/confirm_email/" in w][0]
    r = mail_on.get(link.replace("http://localhost", ""))
    assert r.status_code == 302
    assert User.query.filter_by(username="alice").one().email == "alice@x.org"


@pytest.mark.parametrize("bad", ["", "no-at-sign", "root@x.org"])
def test_complete_email_validates_like_registration(mail_on, bad):
    _no_email_user(); _login(mail_on, "alice")
    with mail.record_messages() as out:
        mail_on.post("/complete_email", data={"email": bad})
    assert out == []


def test_bad_confirmation_token_changes_nothing(mail_on):
    _no_email_user(); _login(mail_on, "alice")
    mail_on.get("/confirm_email/garbage")
    assert User.query.filter_by(username="alice").one().email is None


def test_profile_email_change_is_parked_until_confirmed_when_mail_is_on(mail_on):
    _login(mail_on)
    with mail.record_messages() as out:
        _profile_post(mail_on, email="new@x.org")
        import time; time.sleep(0.2)
    assert User.query.filter_by(username="root").one().email == "root@x.org"
    assert out and out[0].recipients == ["new@x.org"]
    _profile_post(mail_on, email="")          # clearing is refused
    assert User.query.filter_by(username="root").one().email == "root@x.org"
