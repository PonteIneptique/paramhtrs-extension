from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint
from flask import current_app
import click
import json
from .process import from_xml_to_tei
db = SQLAlchemy()


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

@db_cli.command("init")
def init_db_command():
    """Initialize the database."""
    with current_app.app_context():
        db.create_all()
        click.echo("Initialized the database.")
