from flask import Flask
import os.path

app = Flask(
    __name__
)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///./lines.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from .models import db, db_cli, Line
db.init_app(app)
app.cli.add_command(db_cli)

from .process import import_text
app.cli.add_command(import_text)

from .bp_main import bp_main
app.register_blueprint(bp_main)

if __name__ == "__main__":
    app.run(debug=True)
