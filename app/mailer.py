"""Optional outgoing mail.

Mail is on only when MAIL_SERVER is configured; every caller must cope with it
being off (`mail_enabled()`), so the app stays usable without an SMTP server.
Messages are sent from a background thread so a slow SMTP server never blocks a
request, and a delivery failure is logged rather than raised.
"""
import logging
from threading import Thread

from flask import current_app, render_template
from flask_mail import Mail, Message
from itsdangerous import BadData, URLSafeTimedSerializer

mail = Mail()
logger = logging.getLogger(__name__)

_RESET_SALT = "password-reset"


def mail_enabled() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def _deliver(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception:  # SMTP is best-effort: never take a request down with it
            logger.exception("Could not send mail %r to %s", msg.subject, msg.recipients)


def send_email(recipients, subject, template, **context) -> bool:
    """Render `email/<template>.txt` and send it. Returns False when mail is off
    or there is nobody to send to."""
    recipients = [r for r in dict.fromkeys(recipients or []) if r]
    if not mail_enabled() or not recipients:
        return False
    app = current_app._get_current_object()
    msg = Message(
        f"[{app.config['APP_NAME']}] {subject}",
        sender=app.config.get("MAIL_DEFAULT_SENDER"),
        recipients=recipients,
        body=render_template(f"email/{template}.txt", app_name=app.config["APP_NAME"], **context),
    )
    Thread(target=_deliver, args=(app, msg), daemon=True).start()
    return True


def admin_recipients():
    from .models import User
    emails = [u.email for u in User.query.filter_by(is_admin=True, is_approved=True) if u.email]
    if current_app.config.get("ADMIN_EMAIL"):
        emails.append(current_app.config["ADMIN_EMAIL"])
    return emails


# ── Password-reset tokens ─────────────────────────────────────────────────────
# Signed with SECRET_KEY, time-limited, and bound to the current password hash:
# using the link (or changing the password any other way) invalidates it.

def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_RESET_SALT)


def _fingerprint(user) -> str:
    return user.password_hash[-12:]


def make_reset_token(user) -> str:
    return _serializer().dumps({"uid": user.id, "pw": _fingerprint(user)})


def user_from_reset_token(token):
    from .models import User, db
    try:
        data = _serializer().loads(token, max_age=current_app.config["RESET_TOKEN_MAX_AGE"])
    except BadData:
        return None
    user = db.session.get(User, data.get("uid"))
    if user is None or data.get("pw") != _fingerprint(user):
        return None
    return user


# ── Email-confirmation tokens ─────────────────────────────────────────────────
# An address is only stored on the account once its owner has followed a link
# mailed to it. The token carries the address itself, so nothing is persisted
# (no schema change) until the click, and it dies with the reset window.

_EMAIL_SALT = "email-confirm"


def make_email_token(user, email: str) -> str:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_EMAIL_SALT).dumps(
        {"uid": user.id, "email": email})


def email_from_token(token):
    """-> (user, email) for a valid, unexpired token, else None."""
    from .models import User, db
    try:
        data = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_EMAIL_SALT).loads(
            token, max_age=current_app.config["RESET_TOKEN_MAX_AGE"])
    except BadData:
        return None
    user = db.session.get(User, data.get("uid"))
    return (user, data["email"]) if user and data.get("email") else None
