from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint
from flask import current_app
import click
db = SQLAlchemy()

# -------------------------
# Database model
# -------------------------
class Line(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_text = db.Column(db.Text, nullable=False, unique=True)
    xml = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'done')",
            name="check_status_valid"
        ),
    )

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
