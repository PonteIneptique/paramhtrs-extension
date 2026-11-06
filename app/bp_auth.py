from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_user, logout_user, current_user
from .models import User, db, AppSetting, CERT_CHOICES, get_default_cert
from .mailer import (mail_enabled, send_email, admin_recipients,
                     make_reset_token, user_from_reset_token,
                     make_email_token, email_from_token)
from flask_login import LoginManager, login_required



login_manager = LoginManager()

bp_auth = Blueprint('bp_auth', __name__)


@bp_auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index_route"))

    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if user.is_approved:
                login_user(user)
                return redirect(url_for("index_route"))
            else:
                flash("Account not approved by admin.", "danger")
        else:
            flash("Invalid username or password.", "danger")

    return render_template("auth/login.html", mail_enabled=mail_enabled())


@bp_auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("bp_auth.login"))


@bp_auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form['username'].strip()
        password = request.form['password']
        email = request.form.get('email', '').strip().lower() or None

        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
        elif mail_enabled() and not email:
            flash("An email address is required.", "danger")
        elif email and "@" not in email:
            flash("That email address looks invalid.", "danger")
        elif email and User.query.filter_by(email=email).first():
            flash("That email address is already registered.", "danger")
        else:
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            send_email(admin_recipients(), f"New account awaiting approval: {username}", "new_user",
                       username=username, email=email,
                       admin_url=url_for("bp_auth.admin_panel", _external=True))
            flash("Account created. Waiting for admin approval.", "success")
            return redirect(url_for("bp_auth.login"))

    return render_template("auth/register.html", mail_enabled=mail_enabled())


@bp_auth.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if not mail_enabled():
        flash("Password reset by email is not available here; ask an administrator.", "warning")
        return redirect(url_for("bp_auth.login"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user and user.is_approved:
            send_email([user.email], "Reset your password", "reset_password", user=user,
                       reset_link=url_for("bp_auth.reset_password", token=make_reset_token(user), _external=True),
                       minutes=current_app.config["RESET_TOKEN_MAX_AGE"] // 60)
        # Same answer whether or not the address is known: don't leak who has an account.
        flash("If that address belongs to an account, a reset link is on its way.", "info")
        return redirect(url_for("bp_auth.login"))
    return render_template("auth/forgot_password.html")


@bp_auth.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = user_from_reset_token(token)
    if user is None:
        flash("That reset link is invalid or has expired.", "danger")
        return redirect(url_for("bp_auth.forgot_password" if mail_enabled() else "bp_auth.login"))
    if request.method == "POST":
        password = request.form.get("new_password", "")
        if not password or password != request.form.get("confirm_password"):
            flash("Passwords are empty or do not match.", "danger")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Password updated. You can log in now.", "success")
            return redirect(url_for("bp_auth.login"))
    return render_template("auth/reset_password.html", token=token)

# Admin route to approve or reject users
@bp_auth.route("/admin/approve_user/<int:user_id>", methods=["POST"])
@login_required
def approve_user(user_id):
    if not current_user.is_admin:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for("index_route"))

    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    send_email([user.email], "Your account was approved", "approved", user=user,
               login_url=url_for("bp_auth.login", _external=True))
    flash(f"User {user.username} has been approved.", "success")
    return redirect(url_for("index_route"))

# Admin route to reject users
@bp_auth.route("/admin/reject_user/<int:user_id>", methods=["POST"])
@login_required
def reject_user(user_id):
    if not current_user.is_admin:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for("index_route"))

    user = User.query.get_or_404(user_id)
    username, email = user.username, user.email
    db.session.delete(user)
    db.session.commit()
    send_email([email], "Your registration was not approved", "rejected", username=username)
    flash(f"User {username} has been rejected.", "success")
    return redirect(url_for("index_route"))

@bp_auth.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    # The form lives on the profile page; GET is kept so old links still work.
    if request.method == "POST":
        if not current_user.check_password(request.form.get("old_password", "")):
            flash("Old password is incorrect.", "danger")
        elif not request.form.get("new_password"):
            flash("New password cannot be empty.", "danger")
        elif request.form["new_password"] != request.form.get("confirm_password"):
            flash("New passwords do not match.", "danger")
        else:
            current_user.set_password(request.form["new_password"])
            db.session.commit()
            flash("Your password has been updated successfully.", "success")
    return redirect(url_for("bp_auth.profile"))

# ── Email completion / confirmation ───────────────────────────────────────────
# With mail on, every account needs a confirmed address. Someone without one is
# sent to /complete_email (page navigations only — fetch() calls are left alone).

_EMAIL_EXEMPT = {"bp_auth.complete_email", "bp_auth.confirm_email", "bp_auth.logout", "static"}


@bp_auth.before_app_request
def require_email():
    if (mail_enabled() and current_user.is_authenticated and not current_user.email
            and request.method == "GET" and request.endpoint not in _EMAIL_EXEMPT
            and "text/html" in request.headers.get("Accept", "")):
        return redirect(url_for("bp_auth.complete_email"))


def validate_new_email(raw, user):
    """Same rules as registration. Returns (email, error)."""
    email = (raw or "").strip().lower()
    if not email:
        return None, "An email address is required."
    if "@" not in email:
        return None, "That email address looks invalid."
    other = User.query.filter(User.email == email, User.id != user.id).first()
    if other:
        return None, "That email address is already registered."
    return email, None


def send_confirmation(user, email):
    minutes = current_app.config["RESET_TOKEN_MAX_AGE"] // 60
    return send_email([email], "Confirm your email address", "confirm_email", user=user, minutes=minutes,
                      confirm_link=url_for("bp_auth.confirm_email", token=make_email_token(user, email),
                                           _external=True))


@bp_auth.route("/complete_email", methods=["GET", "POST"])
@login_required
def complete_email():
    if not mail_enabled() or current_user.email:
        return redirect(url_for("bp_auth.profile"))
    sent_to = None
    if request.method == "POST":
        email, error = validate_new_email(request.form.get("email"), current_user)
        if error:
            flash(error, "danger")
        else:
            send_confirmation(current_user, email)
            sent_to = email
    return render_template("auth/complete_email.html", sent_to=sent_to)


@bp_auth.route("/confirm_email/<token>")
def confirm_email(token):
    found = email_from_token(token)
    if not found:
        flash("This confirmation link is invalid or has expired.", "danger")
        return redirect(url_for("bp_auth.profile" if current_user.is_authenticated else "bp_auth.login"))
    user, email = found
    if User.query.filter(User.email == email, User.id != user.id).first():
        flash("That email address is already registered.", "danger")
    else:
        user.email = email
        db.session.commit()
        flash("Email address confirmed.", "success")
    return redirect(url_for("bp_auth.profile" if current_user.is_authenticated else "bp_auth.login"))


@bp_auth.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username or len(username) > 80:
            flash("Username is required (80 characters max).", "danger")
            return redirect(url_for("bp_auth.profile"))
        if username != current_user.username and User.query.filter(User.username == username).first():
            flash("That username is already taken.", "danger")
            return redirect(url_for("bp_auth.profile"))
        current_user.username    = username
        current_user.first_name  = request.form.get("first_name",  "").strip() or None
        current_user.last_name   = request.form.get("last_name",   "").strip() or None
        current_user.orcid       = request.form.get("orcid",       "").strip() or None
        current_user.institution = request.form.get("institution", "").strip() or None
        email = request.form.get("email", "").strip().lower() or None
        if email and User.query.filter(User.email == email, User.id != current_user.id).first():
            flash("That email address is already in use.", "danger")
            return redirect(url_for("bp_auth.profile"))
        confirm_email_to = None
        if mail_enabled():
            # A mail-enabled instance keeps only confirmed addresses: a change is
            # parked until its owner follows the link, and clearing is refused.
            if not email:
                flash("An email address is required.", "danger")
                return redirect(url_for("bp_auth.profile"))
            if email != current_user.email:
                confirm_email_to = email
        else:
            current_user.email = email
        nickname = request.form.get("nickname", "").strip() or None
        if nickname and nickname != current_user.nickname:
            taken = User.query.filter(User.nickname == nickname, User.id != current_user.id).first()
            if taken:
                flash("That nickname is already in use.", "danger")
                return redirect(url_for("bp_auth.profile"))
        current_user.nickname = nickname
        db.session.commit()
        if confirm_email_to:
            send_confirmation(current_user, confirm_email_to)
            flash(f"Profile updated. Follow the link we sent to {confirm_email_to} to confirm the new address.", "success")
        else:
            flash("Profile updated.", "success")
        return redirect(url_for("bp_auth.profile"))
    return render_template("auth/profile.html", mail_enabled=mail_enabled())


@bp_auth.route("/admin", methods=["GET", "POST"])
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash("You are not authorized to access the admin panel.", "danger")
        return redirect(url_for("index_route"))

    # Handle password update request
    if request.method == "POST":
        user_id = request.form.get("user_id")
        new_password = request.form.get("new_password")

        if request.form.get("default_cert"):
            cert = request.form["default_cert"]
            if cert in CERT_CHOICES:
                AppSetting.set("default_cert", cert)
                db.session.commit()
                flash("Default certainty updated.", "success")
            else:
                flash("Unknown certainty.", "danger")
        elif user_id and new_password:
            user = User.query.get(user_id)
            if user and user.is_approved:
                user.set_password(new_password)  # Hash and update password
                db.session.commit()
                flash(f"Password updated for {user.username}.", "success")
            else:
                flash("User not found or not approved.", "danger")
        else:
            flash("Invalid input for password update.", "danger")

    # Get unapproved users
    unapproved_users = User.query.filter_by(is_approved=False).all()
    # Get approved users
    approved_users = User.query.filter_by(is_approved=True).all()

    return render_template("auth/admin.html", unapproved_users=unapproved_users, approved_users=approved_users,
                           mail_enabled=mail_enabled(), default_cert=get_default_cert(),
                           cert_choices=CERT_CHOICES)


# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def requires_access(cls, id_arg_name: str):
    """
    Flask decorator to require access to an object of class `cls` based on an ID from the route.

    Args:
        cls: The SQLAlchemy model class (e.g., Project, Alignment).
        id_arg_name: The name of the argument in the route that contains the object's ID.

    Returns:
        The object is passed as the first argument to the decorated function if access is allowed.
    """

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Get the ID from kwargs
            obj_id = kwargs.get(id_arg_name)
            if obj_id is None:
                abort(400, f"Missing {id_arg_name} in route")

            # Retrieve the object
            obj = cls.query.get(obj_id)
            if obj is None:
                abort(404, f"{cls.__name__} with id {obj_id} not found")

            # Unauthenticated users get redirected to login; authenticated but
            # unauthorised users get 403.
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if not obj.user_has_access(current_user):
                abort(403, f"You do not have access to this {cls.__name__}")

            # Remove the ID from kwargs and replace with the object
            kwargs.pop(id_arg_name)
            return f(obj, *args, **kwargs)

        return wrapped

    return decorator
