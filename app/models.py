from sqlalchemy import CheckConstraint
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

import click
import json
from .process import from_xml_to_tei


db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    normalizations = db.relationship(
        "Normalization",
        backref="project",
        cascade="all, delete-orphan",
        lazy=True,
    )



# -------------------------
# Database model
# -------------------------
class Normalization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_text = db.Column(db.Text, nullable=False, unique=True)
    xml = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'done')",
            name="check_status_valid"
        ),
    )

    @property
    def name(self):
        return self.original_text[:80]

    @property
    def json_compatible(self):
        return {
            'metadata': json.loads(self.metadata_json),
            'id': self.id,
            'orig': self.original_text,
            'norm': self.normalized_text,
            'status': self.status
        }

    @property
    def normalized_text(self):
        return from_xml_to_tei(self.xml, plaintext=True)

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
            admin = User(username=admin_name, is_admin=True, is_approved=True)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            click.echo("Admin created")


@db_cli.command("reset")
def db_create():
    with current_app.app_context():
        db.drop_all()
        db.create_all()
    click.echo("DB Recreated")

@db_cli.command("drop")
def db_create():
    with current_app.app_context():
        db.drop_all()
    click.echo("DB Dropped")