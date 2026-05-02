from sqlalchemy import CheckConstraint, inspect, text
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

import click
import json


db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin      = db.Column(db.Boolean, default=False)
    is_approved   = db.Column(db.Boolean, default=False)
    # Profile fields (all optional)
    first_name    = db.Column(db.String(100), nullable=True)
    last_name     = db.Column(db.String(100), nullable=True)
    nickname      = db.Column(db.String(80),  nullable=True, unique=True)  # used as TEI @resp key
    orcid         = db.Column(db.String(30),  nullable=True)
    institution   = db.Column(db.String(200), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Work(db.Model):
    __tablename__ = "works"
    id    = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    genre = db.Column(db.String(100), nullable=True)


class DocumentWork(db.Model):
    __tablename__ = "document_work"
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)
    work_id     = db.Column(db.Integer, db.ForeignKey("works.id"),     primary_key=True)


class PageWork(db.Model):
    __tablename__ = "page_work"
    page_id = db.Column(db.Integer, db.ForeignKey("pages.id"), primary_key=True)
    work_id = db.Column(db.Integer, db.ForeignKey("works.id"), primary_key=True)


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

    def user_has_access(self, user) -> bool:
        if not getattr(user, 'is_authenticated', False):
            return False
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
    iiif_manifest_url = db.Column(db.Text, nullable=True)

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

    works = db.relationship(
        "Work",
        secondary="document_work",
        backref=db.backref("documents", lazy="dynamic"),
        lazy="dynamic",
    )

    def user_has_access(self, user) -> bool:
        if not getattr(user, 'is_authenticated', False):
            return False
        project = Project.query.get(self.project_id)
        if project.user_has_access(user):
            return True
        return DocumentUser.query.filter(
            DocumentUser.document_id == self.id,
            DocumentUser.user_id == user.id
        ).count() > 0


class Annotation(db.Model):
    __tablename__ = "annotations"

    id            = db.Column(db.String(36),  primary_key=True)
    page_id       = db.Column(db.Integer, db.ForeignKey("pages.id"), nullable=False, index=True)
    body_value    = db.Column(db.Text,        nullable=True)
    body_purpose  = db.Column(db.String(50),  nullable=True)
    body_reason   = db.Column(db.String(50),  nullable=True)
    target_start  = db.Column(db.Integer,     nullable=False, default=0)
    target_end    = db.Column(db.Integer,     nullable=False, default=0)
    target_exact  = db.Column(db.Text,        nullable=True)
    target_prefix = db.Column(db.Text,        nullable=True)
    target_suffix = db.Column(db.Text,        nullable=True)
    resp_id       = db.Column(db.Integer,     nullable=True)
    validated_by  = db.Column(db.Integer,     nullable=True)

    page = db.relationship("Page", back_populates="annotation_rows")

    def to_dict(self) -> dict:
        body_entry = {"type": "TextualBody",
                      "value":   self.body_value   or "",
                      "purpose": self.body_purpose or "normalizing"}
        if self.body_reason:
            body_entry["reason"] = self.body_reason
        d = {
            "id":   self.id,
            "type": "Annotation",
            "body": [body_entry],
            "target": {
                "annotation": self.id,
                "selector": [
                    {"type": "TextPositionSelector",
                     "start": self.target_start, "end": self.target_end},
                    {"type": "TextQuoteSelector",
                     "exact":  self.target_exact  or "",
                     "prefix": self.target_prefix or "",
                     "suffix": self.target_suffix or ""},
                ],
            },
        }
        if self.resp_id      is not None: d["resp_id"]     = self.resp_id
        if self.validated_by is not None: d["validated_by"] = self.validated_by
        return d

    @classmethod
    def from_dict(cls, page_id: int, data: dict) -> "Annotation":
        sel  = data.get("target", {}).get("selector", [])
        pos  = next((s for s in sel if s.get("type") == "TextPositionSelector"), {})
        quo  = next((s for s in sel if s.get("type") == "TextQuoteSelector"),    {})
        body = (data.get("body") or [{}])[0]
        return cls(
            id           = data["id"],
            page_id      = page_id,
            body_value   = body.get("value"),
            body_purpose = body.get("purpose"),
            body_reason  = body.get("reason"),
            target_start = pos.get("start", 0),
            target_end   = pos.get("end",   0),
            target_exact = quo.get("exact"),
            target_prefix= quo.get("prefix"),
            target_suffix= quo.get("suffix"),
            resp_id      = data.get("resp_id"),
            validated_by = data.get("validated_by"),
        )

    @classmethod
    def upsert_from_dict(cls, page_id: int, data: dict) -> None:
        """Update existing row or insert new one from a W3C annotation dict."""
        existing = cls.query.filter_by(id=data["id"], page_id=page_id).first()
        if existing:
            sel  = data.get("target", {}).get("selector", [])
            pos  = next((s for s in sel if s.get("type") == "TextPositionSelector"), {})
            quo  = next((s for s in sel if s.get("type") == "TextQuoteSelector"),    {})
            body = (data.get("body") or [{}])[0]
            existing.body_value   = body.get("value")
            existing.body_purpose = body.get("purpose")
            existing.body_reason  = body.get("reason")
            existing.target_start = pos.get("start", 0)
            existing.target_end   = pos.get("end",   0)
            existing.target_exact = quo.get("exact")
            existing.target_prefix= quo.get("prefix")
            existing.target_suffix= quo.get("suffix")
            existing.resp_id      = data.get("resp_id")
            existing.validated_by = data.get("validated_by")
        else:
            db.session.add(cls.from_dict(page_id, data))


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

    annotation_rows = db.relationship(
        "Annotation",
        back_populates="page",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Annotation.target_start",
    )

    @property
    def annotations(self) -> list:
        return [a.to_dict() for a in self.annotation_rows]

    def set_annotations(self, annots: list) -> None:
        """Replace all annotations for this page."""
        Annotation.query.filter_by(page_id=self.id).delete(synchronize_session=False)
        for data in annots:
            db.session.add(Annotation.from_dict(self.id, data))

    works = db.relationship(
        "Work",
        secondary="page_work",
        backref=db.backref("pages", lazy="dynamic"),
        lazy="dynamic",
    )

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

@click.group("dbmgmt")
def db_cli():
    """Legacy database management commands (create/reset/drop/upgrade/migrate-annotations)"""
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


@db_cli.command("list-users")
def db_list_users():
    """List all registered users."""
    with current_app.app_context():
        users = User.query.order_by(User.id).all()
        if not users:
            click.echo("No users found.")
            return
        click.echo(f"{'ID':<6} {'Username':<30} {'Nickname':<20} {'Admin':<6} {'Approved'}")
        click.echo("-" * 70)
        for u in users:
            click.echo(f"{u.id:<6} {u.username:<30} {(u.nickname or ''):<20} {'yes' if u.is_admin else 'no':<6} {'yes' if u.is_approved else 'no'}")


@db_cli.command("change-password")
@click.argument("username")
@click.option("--password", default=None, help="New password (prompted if omitted).")
def db_change_password(username, password):
    """Change the password for USERNAME."""
    with current_app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            raise click.ClickException(f"No user found with username '{username}'.")
        if not password:
            password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        user.set_password(password)
        db.session.commit()
        click.echo(f"Password updated for '{username}'.")


@db_cli.command("upgrade")
def db_upgrade():
    """Add any missing columns/tables to an existing database."""
    with current_app.app_context():
        inspector = inspect(db.engine)

        # New tables (handled by create_all)
        db.create_all()
        click.echo("New tables created (if any)")

        # Columns to add: (table_name, column_name, column_def)
        new_columns = [
            ("users",       "first_name",        "VARCHAR(100)"),
            ("users",       "last_name",          "VARCHAR(100)"),
            ("users",       "nickname",           "VARCHAR(80)"),
            ("users",       "orcid",              "VARCHAR(30)"),
            ("users",       "institution",        "VARCHAR(200)"),
            ("documents",   "iiif_manifest_url",  "TEXT"),
            ("annotations", "body_reason",        "VARCHAR(50)"),
        ]
        for table, col, col_def in new_columns:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if col not in existing:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                click.echo(f"  Added {table}.{col}")
            else:
                click.echo(f"  {table}.{col} already exists — skipped")

        db.session.commit()
        click.echo("Upgrade complete")


@db_cli.command("migrate-annotations")
def db_migrate_annotations():
    """Migrate page.annotations JSON column to the annotations table."""
    with current_app.app_context():
        db.create_all()
        click.echo("Ensuring annotations table exists...")

        result = db.session.execute(text("SELECT id, annotations FROM pages")).fetchall()
        total = 0
        skipped = 0
        for page_id, ann_json in result:
            if not ann_json:
                continue
            annots = json.loads(ann_json) if isinstance(ann_json, str) else ann_json
            if not annots:
                continue
            existing = Annotation.query.filter_by(page_id=page_id).count()
            if existing:
                click.echo(f"  Page {page_id}: {existing} rows already present — skipping")
                skipped += 1
                continue
            for ann_data in annots:
                try:
                    db.session.add(Annotation.from_dict(page_id, ann_data))
                except Exception as exc:
                    click.echo(f"  WARNING page {page_id} / ann {ann_data.get('id')}: {exc}")
            total += len(annots)
            click.echo(f"  Page {page_id}: {len(annots)} annotations")

        db.session.commit()
        click.echo(f"Migrated {total} annotations across {len(result) - skipped} pages.")

        try:
            db.session.execute(text("ALTER TABLE pages DROP COLUMN annotations"))
            db.session.commit()
            click.echo("Dropped pages.annotations column.")
        except Exception as exc:
            click.echo(f"Could not drop pages.annotations column (safe to ignore): {exc}")
