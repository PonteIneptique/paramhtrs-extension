from sqlalchemy import CheckConstraint, inspect, text
from sqlalchemy.orm import declared_attr
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


class MetadataWork(db.Model):
    __tablename__ = "metadata_work"
    metadata_id = db.Column(db.Integer, db.ForeignKey("metadata.id"), primary_key=True)
    work_id     = db.Column(db.Integer, db.ForeignKey("works.id"),    primary_key=True)


class Metadata(db.Model):
    """Standalone metadata object — language/QID/filename/IIIF/works — that any
    Folder, Document, or Part can be linked to via a nullable metadata_id FK
    (see HasMetadataMixin). Kept separate from the structural models so it can
    eventually be shared/reused across entries, not just owned 1:1."""
    __tablename__ = "metadata"
    id = db.Column(db.Integer, primary_key=True)
    language = db.Column(db.String(10), nullable=True)
    qid = db.Column(db.String(100), nullable=True)
    original_filename = db.Column(db.String(500), nullable=True)
    iiif_manifest_url = db.Column(db.Text, nullable=True)

    works = db.relationship(
        "Work",
        secondary="metadata_work",
        backref=db.backref("metadata_entries", lazy="dynamic"),
        lazy="dynamic",
    )


class HasMetadataMixin:
    """Adds an optional, lazily-created link to a Metadata row."""

    @declared_attr
    def metadata_id(cls):
        return db.Column(db.Integer, db.ForeignKey("metadata.id"), nullable=True)

    @declared_attr
    def metadata_(cls):
        return db.relationship("Metadata")

    def get_or_create_metadata(self) -> "Metadata":
        if self.metadata_ is None:
            self.metadata_ = Metadata()
            db.session.add(self.metadata_)
        return self.metadata_

    @property
    def works(self) -> list:
        return list(self.metadata_.works.all()) if self.metadata_ else []

    def add_work(self, work: "Work") -> None:
        self.get_or_create_metadata().works.append(work)

    def remove_work(self, work_id: int) -> None:
        if not self.metadata_:
            return
        work = Work.query.get(work_id)
        if work:
            self.metadata_.works.remove(work)


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

    folders = db.relationship(
        "Folder",
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


class FolderUser(db.Model):
    __tablename__ = "folder_user"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("folders.id"), primary_key=True)


class Folder(HasMetadataMixin, db.Model):
    __tablename__ = "folders"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    documents = db.relationship(
        "Document",
        backref="folder",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Document.order"
    )
    users = db.relationship(
        "User",
        secondary="folder_user",
        lazy="dynamic"
    )

    @property
    def language(self):
        return self.metadata_.language if self.metadata_ else "fre"

    @language.setter
    def language(self, value):
        self.get_or_create_metadata().language = value

    @property
    def qid(self):
        return self.metadata_.qid if self.metadata_ else None

    @qid.setter
    def qid(self, value):
        self.get_or_create_metadata().qid = value

    @property
    def iiif_manifest_url(self):
        return self.metadata_.iiif_manifest_url if self.metadata_ else None

    @iiif_manifest_url.setter
    def iiif_manifest_url(self, value):
        self.get_or_create_metadata().iiif_manifest_url = value

    def user_has_access(self, user) -> bool:
        if not getattr(user, 'is_authenticated', False):
            return False
        project = Project.query.get(self.project_id)
        if project.user_has_access(user):
            return True
        return FolderUser.query.filter(
            FolderUser.folder_id == self.id,
            FolderUser.user_id == user.id
        ).count() > 0


class Annotation(db.Model):
    __tablename__ = "annotations"

    id            = db.Column(db.String(36),  primary_key=True)
    document_id   = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    body_value    = db.Column(db.Text,        nullable=True)
    body_purpose  = db.Column(db.String(50),  nullable=True)
    body_reason   = db.Column(db.String(50),  nullable=True)
    body_semtag   = db.Column(db.String(50),  nullable=True)
    target_start  = db.Column(db.Integer,     nullable=False, default=0)
    target_end    = db.Column(db.Integer,     nullable=False, default=0)
    target_exact  = db.Column(db.Text,        nullable=True)
    target_prefix = db.Column(db.Text,        nullable=True)
    target_suffix = db.Column(db.Text,        nullable=True)
    resp_id       = db.Column(db.Integer,     nullable=True)
    validated_by  = db.Column(db.Integer,     nullable=True)
    body_gap_before = db.Column(db.Boolean,   nullable=False, default=False)
    body_gap_after  = db.Column(db.Boolean,   nullable=False, default=False)

    document = db.relationship("Document", back_populates="annotation_rows")

    def to_dict(self) -> dict:
        body_entry = {"type": "TextualBody",
                      "value":   self.body_value   or "",
                      "purpose": self.body_purpose or "normalizing"}
        if self.body_reason:
            body_entry["reason"] = self.body_reason
        if self.body_semtag:
            body_entry["semtag"] = self.body_semtag
        if self.body_gap_before:
            body_entry["gap_before"] = True
        if self.body_gap_after:
            body_entry["gap_after"] = True
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
    def from_dict(cls, document_id: int, data: dict) -> "Annotation":
        sel  = data.get("target", {}).get("selector", [])
        pos  = next((s for s in sel if s.get("type") == "TextPositionSelector"), {})
        quo  = next((s for s in sel if s.get("type") == "TextQuoteSelector"),    {})
        body = (data.get("body") or [{}])[0]
        return cls(
            id           = data["id"],
            document_id  = document_id,
            body_value   = body.get("value"),
            body_purpose = body.get("purpose"),
            body_reason  = body.get("reason"),
            body_semtag  = body.get("semtag"),
            target_start = pos.get("start", 0),
            target_end   = pos.get("end",   0),
            target_exact = quo.get("exact"),
            target_prefix= quo.get("prefix"),
            target_suffix= quo.get("suffix"),
            resp_id      = data.get("resp_id"),
            validated_by = data.get("validated_by"),
            body_gap_before = body.get("gap_before", False),
            body_gap_after  = body.get("gap_after", False),
        )

    @classmethod
    def upsert_from_dict(cls, document_id: int, data: dict) -> None:
        """Update existing row or insert new one from a W3C annotation dict."""
        existing = cls.query.filter_by(id=data["id"], document_id=document_id).first()
        if existing:
            sel  = data.get("target", {}).get("selector", [])
            pos  = next((s for s in sel if s.get("type") == "TextPositionSelector"), {})
            quo  = next((s for s in sel if s.get("type") == "TextQuoteSelector"),    {})
            body = (data.get("body") or [{}])[0]
            existing.body_value   = body.get("value")
            existing.body_purpose = body.get("purpose")
            existing.body_reason  = body.get("reason")
            existing.body_semtag  = body.get("semtag")
            existing.target_start = pos.get("start", 0)
            existing.target_end   = pos.get("end",   0)
            existing.target_exact = quo.get("exact")
            existing.target_prefix= quo.get("prefix")
            existing.target_suffix= quo.get("suffix")
            existing.resp_id      = data.get("resp_id")
            existing.validated_by = data.get("validated_by")
            existing.body_gap_before = body.get("gap_before", False)
            existing.body_gap_after  = body.get("gap_after", False)
        else:
            db.session.add(cls.from_dict(document_id, data))


class Document(HasMetadataMixin, db.Model):
    """The continuous, annotatable text unit (formerly 'Page', then 'Part') —
    shown in a Folder's browse list and edited in the 3-panel editor. Made up
    of one or more Parts (formerly 'Subpart')."""
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("folders.id"), nullable=False)
    label = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'done', 'for_review')",
            name="check_document_status_valid"
        ),
    )

    annotation_rows = db.relationship(
        "Annotation",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Annotation.target_start",
    )

    @property
    def annotations(self) -> list:
        return [a.to_dict() for a in self.annotation_rows]

    def set_annotations(self, annots: list) -> None:
        """Replace all annotations for this document."""
        Annotation.query.filter_by(document_id=self.id).delete(synchronize_session=False)
        for data in annots:
            db.session.add(Annotation.from_dict(self.id, data))

    parts = db.relationship(
        "Part",
        backref="document",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Part.order"
    )

    @property
    def qid(self):
        return self.metadata_.qid if self.metadata_ else None

    @qid.setter
    def qid(self, value):
        self.get_or_create_metadata().qid = value

    @property
    def lines(self) -> list:
        """All lines across all parts, in part/line order."""
        return [line for part in self.parts for line in part.lines]

    @property
    def full_text(self) -> str:
        """Original text of all lines (across all parts) joined by newline."""
        return "\n".join(line.original_text for line in self.lines)

    @property
    def normalized_text(self) -> str:
        from .annot_utils import apply_annotations_to_text
        return apply_annotations_to_text(self.full_text, self.annotations or [])

    @property
    def line_offsets(self) -> list:
        """List of {start, alto_id} giving each line's start offset within full_text,
        used to attach ALTO line ids to <lb/> tags in TEI export."""
        offsets = []
        offset = 0
        for line in self.lines:
            offsets.append({"start": offset, "alto_id": line.alto_id})
            offset += len(line.original_text) + 1
        return offsets

    @property
    def part_offsets(self) -> list:
        """List of {start, part_id, original_filename} giving each part's
        start offset within full_text, used to mark part boundaries (e.g. as
        <milestone/> in TEI export) when a Document is made of several parts."""
        offsets = []
        offset = 0
        for part in self.parts:
            offsets.append({
                "start": offset,
                "part_id": part.id,
                "original_filename": part.original_filename,
            })
            for line in part.lines:
                offset += len(line.original_text) + 1
        return offsets

    def user_has_access(self, user: User) -> bool:
        folder = Folder.query.get(self.folder_id)
        return folder.user_has_access(user)

    @property
    def prev(self):
        return (
            Document.query
            .filter(Document.folder_id == self.folder_id, Document.order < self.order)
            .order_by(Document.order.desc())
            .first()
        )

    @property
    def next(self):
        return (
            Document.query
            .filter(Document.folder_id == self.folder_id, Document.order > self.order)
            .order_by(Document.order.asc())
            .first()
        )

    @property
    def line_count(self):
        return sum(len(part.lines) for part in self.parts)

    @property
    def original_filename(self):
        """Filename of the first part, for display/editing in the common
        single-part case. Multi-part documents manage filenames per part."""
        return self.parts[0].original_filename if self.parts else None


class Part(HasMetadataMixin, db.Model):
    """One imported source's lines (formerly 'Subpart') within a Document.
    Most Documents have exactly one Part; several Parts let cleanup/annotation
    span what used to be separate imports as one continuous text."""
    __tablename__ = "parts"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

    lines = db.relationship(
        "Line",
        backref="part",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Line.order"
    )

    @property
    def original_filename(self):
        return self.metadata_.original_filename if self.metadata_ else None

    @original_filename.setter
    def original_filename(self, value):
        self.get_or_create_metadata().original_filename = value

    @property
    def qid(self):
        return self.metadata_.qid if self.metadata_ else None

    @qid.setter
    def qid(self, value):
        self.get_or_create_metadata().qid = value

    def user_has_access(self, user: User) -> bool:
        document = Document.query.get(self.document_id)
        return document.user_has_access(user)


class Line(db.Model):
    __tablename__ = "lines"
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey("parts.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    original_text = db.Column(db.Text, nullable=False)
    alto_id = db.Column(db.String(200), nullable=True)

    def user_has_access(self, user: User) -> bool:
        part = Part.query.get(self.part_id)
        return part.user_has_access(user)


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
            ("annotations", "body_reason",        "VARCHAR(50)"),
            ("annotations", "body_semtag",        "VARCHAR(50)"),
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
    """Migrate document.annotations JSON column to the annotations table (legacy, pre-Document-table schema)."""
    with current_app.app_context():
        db.create_all()
        click.echo("Ensuring annotations table exists...")

        result = db.session.execute(text("SELECT id, annotations FROM documents")).fetchall()
        total = 0
        skipped = 0
        for document_id, ann_json in result:
            if not ann_json:
                continue
            annots = json.loads(ann_json) if isinstance(ann_json, str) else ann_json
            if not annots:
                continue
            existing = Annotation.query.filter_by(document_id=document_id).count()
            if existing:
                click.echo(f"  Document {document_id}: {existing} rows already present — skipping")
                skipped += 1
                continue
            for ann_data in annots:
                try:
                    db.session.add(Annotation.from_dict(document_id, ann_data))
                except Exception as exc:
                    click.echo(f"  WARNING document {document_id} / ann {ann_data.get('id')}: {exc}")
            total += len(annots)
            click.echo(f"  Document {document_id}: {len(annots)} annotations")

        db.session.commit()
        click.echo(f"Migrated {total} annotations across {len(result) - skipped} documents.")

        try:
            db.session.execute(text("ALTER TABLE documents DROP COLUMN annotations"))
            db.session.commit()
            click.echo("Dropped documents.annotations column.")
        except Exception as exc:
            click.echo(f"Could not drop documents.annotations column (safe to ignore): {exc}")
