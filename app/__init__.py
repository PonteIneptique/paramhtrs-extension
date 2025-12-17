from flask import Flask, current_app, render_template
from flask_login import LoginManager
import click
import os

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///./lines.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEQ2SEQ_MODEL'] = os.path.join(app.root_path, '..', 'model')
app.config['SECRET_KEY'] = 'jfbqh2brbsefonp12294810i23hrisnbfdhbdiauOJSOBSDFDU9 209IEWR'

from .models import db, db_cli, Normalization
db.init_app(app)
app.cli.add_command(db_cli)

# -------------------------
# CLI import function
# -------------------------
@click.command("import-text")
@click.argument("file_path")
def import_text(file_path):
    """Import a plain text file into the DB."""
    from .process import get_model_and_tokenizer, normalize_line, align_to_segs
    model, tokenizer = get_model_and_tokenizer()

    with current_app.app_context():
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                normalized = normalize_line(line, model, tokenizer)
                xml = align_to_segs(line, normalized)
                db.session.add(Normalization(original_text=line, xml=xml, status='pending', metadata_json=json.dumps({})))
        db.session.commit()
        click.echo(f"Imported {file_path} into DB.")

@app.route("/")
def index_route():
    return render_template("index.html")

@app.route("/guidelines")
def guidelines_route():
    return render_template("guidelines.html")

from .bp_norm import bp_norm
app.register_blueprint(bp_norm)

from .bp_project import bp_project
app.register_blueprint(bp_project)

from .bp_auth import login_manager, bp_auth
app.register_blueprint(bp_auth)
login_manager.init_app(app)

if __name__ == "__main__":
    app.run(debug=True)
