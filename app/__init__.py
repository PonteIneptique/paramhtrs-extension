from flask import Flask, render_template
from flask_login import LoginManager
import os

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'template'),
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///./lines.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEQ2SEQ_MODEL'] = "comma-project/normalization-byt5-small"
app.config['MAX_CHUNK_BYTES'] = 512
app.config['SECRET_KEY'] = 'jfbqh2brbsefonp12294810i23hrisnbfdhbdiauOJSOBSDFDU9 209IEWR'

from .models import db, db_cli
db.init_app(app)
app.cli.add_command(db_cli)


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

from .bp_document import bp_document
app.register_blueprint(bp_document)

from .bp_page import bp_page
app.register_blueprint(bp_page)

from .bp_auth import login_manager, bp_auth
app.register_blueprint(bp_auth)
login_manager.init_app(app)

from .bp_comma import bp_comma
app.register_blueprint(bp_comma)

from .bp_cli import cli_group
app.cli.add_command(cli_group)

if __name__ == "__main__":
    app.run(debug=True)
