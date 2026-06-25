"""Forces every test in this suite onto an isolated in-memory SQLite database.

This MUST run before any test module does `from app import app`: Flask-SQLAlchemy
resolves a relative `sqlite:///./lines.db` URI against `app.instance_path` and
binds the engine the first time it's used, so setting `app.config["SQLALCHEMY_DATABASE_URI"]`
*after* import has no effect — it silently leaves tests writing to (and
`db.drop_all()`-ing) the real instance/lines.db. conftest.py is collected by
pytest before any test module is imported, which is what makes setting the
env var here, rather than in a fixture, actually work.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
