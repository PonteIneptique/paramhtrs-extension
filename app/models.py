from sqlalchemy import CheckConstraint
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

import click
import json


db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class ProjectUser(db.Model):
    __tablename__ = "project_user"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), primary_key=True)


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    documents = db.relationship(
        "Document",
        backref="project",
        cascade="all, delete-orphan",
        lazy=True,
    )

    users = db.relationship(
        "User",
        secondary="project_user",
        backref="projects",
        lazy="dynamic"
    )

    def user_has_access(self, user: User) -> bool:
        if self.creator_id == user.id:
            return True
        return ProjectUser.query.filter(
            ProjectUser.project_id == self.id,
            ProjectUser.user_id == user.id
        ).count() > 0


class DocumentUser(db.Model):
    __tablename__ = "document_user"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)


class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    language = db.Column(db.String(10), nullable=False, default="fre")
    qid = db.Column(db.String(100), nullable=True)

    pages = db.relationship(
        "Page",
        backref="document",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Page.order"
    )
    users = db.relationship(
        "User",
        secondary="document_user",
        lazy="dynamic"
    )

    def user_has_access(self, user: User) -> bool:
        project = Project.query.get(self.project_id)
        if project.user_has_access(user):
            return True
        return DocumentUser.query.filter(
            DocumentUser.document_id == self.id,
            DocumentUser.user_id == user.id
        ).count() > 0


class Page(db.Model):
    __tablename__ = "pages"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'done')",
            name="check_page_status_valid"
        ),
    )

    annotations = db.Column(db.JSON, nullable=False, default=list)

    lines = db.relationship(
        "Line",
        backref="page",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Line.order"
    )

    @property
    def full_text(self) -> str:
        """Original text of all lines joined by newline."""
        return "\n".join(line.original_text for line in self.lines)

    @property
    def normalized_text(self) -> str:
        from .annot_utils import apply_annotations_to_text
        return apply_annotations_to_text(self.full_text, self.annotations or [])

    def user_has_access(self, user: User) -> bool:
        document = Document.query.get(self.document_id)
        return document.user_has_access(user)

    @property
    def prev(self):
        return (
            Page.query
            .filter(Page.document_id == self.document_id, Page.order < self.order)
            .order_by(Page.order.desc())
            .first()
        )

    @property
    def next(self):
        return (
            Page.query
            .filter(Page.document_id == self.document_id, Page.order > self.order)
            .order_by(Page.order.asc())
            .first()
        )

    @property
    def line_count(self):
        return Line.query.filter_by(page_id=self.id).count()


class Line(db.Model):
    __tablename__ = "lines"
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey("pages.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    original_text = db.Column(db.Text, nullable=False)
    alto_id = db.Column(db.String(200), nullable=True)

    def user_has_access(self, user: User) -> bool:
        page = Page.query.get(self.page_id)
        return page.user_has_access(user)


# -------------------------
# Flask CLI command to init DB
# -------------------------

@click.group("db")
def db_cli():
    """Database management commands"""
    return ""

@db_cli.command("create")
@click.option("--admin/--no-admin", is_flag=True, default=True)
@click.option("--admin-name", type=str, default="admin")
@click.option("--admin-password", type=str, default="qwerty")
def db_create(admin, admin_name, admin_password):
    with current_app.app_context():
        db.create_all()
        click.echo("DB Created")
        if admin:
            admin_user = User(username=admin_name, is_admin=True, is_approved=True)
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
            click.echo("Admin created")


@db_cli.command("reset")
def db_reset():
    with current_app.app_context():
        db.drop_all()
        db.create_all()
    click.echo("DB Recreated")

@db_cli.command("drop")
def db_drop():
    with current_app.app_context():
        db.drop_all()
    click.echo("DB Dropped")
