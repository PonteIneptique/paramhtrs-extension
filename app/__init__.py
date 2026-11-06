from flask import Flask, render_template
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import os

load_dotenv()

import torch
torch.set_num_threads(int(os.getenv('TORCH_NUM_THREADS', 4)))

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'template'),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///./lines.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEQ2SEQ_MODEL'] = os.getenv('SEQ2SEQ_MODEL', 'comma-project/normalization-byt5-small')
app.config['MODEL_QUANTIZED_PATH'] = os.getenv('MODEL_QUANTIZED_PATH', os.path.join(
    os.path.dirname(__file__), '..', 'model-quantized'))
app.config['MAX_CHUNK_BYTES'] = int(os.getenv('MAX_CHUNK_BYTES', 512))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'jfbqh2brbsefonp12294810i23hrisnbfdhbdiauOJSOBSDFDU9 209IEWR')
app.config['SESSION_COOKIE_NAME'] = os.getenv('SESSION_COOKIE_NAME', 'paramhtr_session')

# ── Mail (optional) ───────────────────────────────────────────────────────────
# Mail is enabled only when MAIL_SERVER is set. Without it the app behaves as
# before: admins approve accounts from the admin panel and reset passwords by hand.
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER') or None
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME') or None
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD') or None
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER') or os.getenv('MAIL_USERNAME') or None
app.config['ADMIN_EMAIL'] = os.getenv('ADMIN_EMAIL') or None   # extra recipient for sign-up notifications
app.config['APP_NAME'] = os.getenv('APP_NAME', 'Abbreviarium')
app.config['RESET_TOKEN_MAX_AGE'] = int(os.getenv('RESET_TOKEN_MAX_AGE', 3600))

from .mailer import mail
mail.init_app(app)

from .models import db, db_cli
from flask_migrate import Migrate
db.init_app(app)
migrate = Migrate(app, db)
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

from .bp_folder import bp_folder
app.register_blueprint(bp_folder)

from .bp_document import bp_document
app.register_blueprint(bp_document)

from .bp_auth import login_manager, bp_auth
app.register_blueprint(bp_auth)
login_manager.init_app(app)
login_manager.login_view = 'bp_auth.login'

from .bp_comma import bp_comma
app.register_blueprint(bp_comma)

from .bp_cli import cli_group, user_cli_group


@app.template_global()
def static_v(filename):
    """url_for('static') plus the file's mtime, so a redeployed script is never
    served stale from a browser or proxy cache."""
    from flask import url_for
    try:
        v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
    except OSError:
        v = 0
    return url_for("static", filename=filename, v=v)

app.cli.add_command(cli_group)
app.cli.add_command(user_cli_group)

from .bp_quantize import quantize_command
app.cli.add_command(quantize_command)

if __name__ == "__main__":
    app.run(debug=True)
