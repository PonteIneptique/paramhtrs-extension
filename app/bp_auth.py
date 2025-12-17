from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from .models import User, db
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

    return render_template("auth/login.html")


@bp_auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("bp_auth.login"))


@bp_auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user:
            flash("Username already taken.", "danger")
        else:
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash("Account created. Waiting for admin approval.", "success")
            return redirect(url_for("bp_auth.login"))

    return render_template("auth/register.html")

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
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} has been rejected.", "success")
    return redirect(url_for("index_route"))

@bp_auth.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form["old_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        # Validate old password
        if not current_user.check_password(old_password):
            flash("Old password is incorrect.", "danger")
            return redirect(url_for("bp_auth.change_password"))

        # Check if new passwords match
        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(url_for("bp_auth.change_password"))

        # Update the password
        current_user.set_password(new_password)
        db.session.commit()

        flash("Your password has been updated successfully.", "success")
        return redirect(url_for("index_route"))

    return render_template("auth/change_password.html")

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

        if user_id and new_password:
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

    return render_template("auth/admin.html", unapproved_users=unapproved_users, approved_users=approved_users)


# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
