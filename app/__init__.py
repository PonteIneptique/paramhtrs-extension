from flask import Flask, current_app
import click

app = Flask(
    __name__
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///./lines.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'jfbqh2brbsefonp12294810i23hrisnbfdhbdiauOJSOBSDFDU9 209IEWR'

from .models import db, db_cli, Line
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
                db.session.add(Line(original_text=line, xml=xml, status='pending', metadata_json=json.dumps({})))
        db.session.commit()
        click.echo(f"Imported {file_path} into DB.")

from .bp_main import bp_main
app.register_blueprint(bp_main)

if __name__ == "__main__":
    app.run(debug=True)
