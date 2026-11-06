# Abbreviarium

Collaborative web editor for normalising medieval manuscript abbreviations produced by Handwritten Text Recognition (HTR) systems.

A seq2seq transformer model suggests modern expansions line by line. Human annotators validate or correct each suggestion directly in the browser. Results are exported as W3C Web Annotations and TEI XML.

## Features

- Page-by-page HTR output editor with source / annotations / normalised-text panels
- Seq2seq normalisation via a HuggingFace Transformers model (streaming progress)
- Character-level alignment engine (via penelopy) mapping abbreviations to their expansions
- Bulk annotation validation: one Ctrl+Enter validates all identical source→target pairs
- Import lines from [CoMMA](https://comma.inria.fr) via Biblissima resource URI
- Export per-page TEI XML (with manuscript metadata) and plain-text zips
- Fine-grained access control: project-level and document-level sharing
- Admin approval workflow for new accounts

## Tech stack

- **Backend**: Python 3.13 · Flask 3 · SQLAlchemy · Flask-Login
- **ML**: [penelopy](https://github.com/PonteIneptique/penelopy) — normalisation model
  loading/inference (PyTorch or ONNX), chunking and the character-level alignment
  engine; wraps HuggingFace Transformers (seq2seq / ByT5)
- **Frontend**: Vue 3 (CDN, Options API) · Bootstrap 5 · Font Awesome
- **XML**: lxml · SaxonC-HE

## Requirements

- Python 3.13
- pip

GPU is optional; the model runs on CPU (set `TORCH_NUM_THREADS` to limit core usage).

## Installation

```bash
git clone <repo-url>
cd paramhtr-editor

python -m venv env
source env/bin/activate

pip install -r requirements.txt
```

## Configuration

Copy the table below into a `.env` file at the project root. All variables have defaults and the app will start without a `.env`.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./lines.db` | SQLAlchemy database URI |
| `SECRET_KEY` | *(insecure built-in)* | Flask session secret — **change in production** |
| `SESSION_COOKIE_NAME` | `paramhtr_session` | Cookie name (change if co-hosting multiple Flask apps) |
| `SEQ2SEQ_MODEL` | `comma-project/normalization-byt5-small` | HuggingFace model ID or local path |
| `MAX_CHUNK_BYTES` | `512` | Maximum bytes per normalisation chunk |
| `TORCH_NUM_THREADS` | `4` | CPU thread limit for PyTorch |
| `MAIL_SERVER` | *(unset)* | SMTP host. **Mail is disabled while unset.** |
| `MAIL_PORT` / `MAIL_USE_TLS` / `MAIL_USE_SSL` | `587` / `true` / `false` | SMTP connection settings |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | *(unset)* | SMTP credentials |
| `MAIL_DEFAULT_SENDER` | `MAIL_USERNAME` | From address |
| `ADMIN_EMAIL` | *(unset)* | Extra recipient for sign-up notifications (admins with an email are always notified) |
| `APP_NAME` | `Abbreviarium` | Name used in mail subjects |
| `RESET_TOKEN_MAX_AGE` | `3600` | Lifetime of a password-reset link, in seconds |

### Mail (optional)

With `MAIL_SERVER` set: registration requires an email, admins are mailed when an account awaits approval, users are mailed on approval/rejection, and "Forgot your password?" sends a single-use, time-limited reset link. Accounts without an email are asked for one at login and must confirm it by link; changing it later in Profile works the same way. Passwords are changed from Profile. Without it, none of this appears and admins manage accounts from the admin panel (`flask user change-password` still works).

## Database initialisation

```bash
flask db create      # create all tables (+ admin account); asks for the default certainty
# flask db create --admin-email me@example.org --default-cert informed
```

The default certainty of new annotations (Normalisation / OCR Fix, Informed, Ambiguous, Arbitrary) is a per-document setting, changed from the editor's Document metadata dialog; `--default-cert` and the admin panel set the instance default that documents fall back to. After upgrading an existing install run `flask db upgrade` (or the Alembic migrations) to add `users.email`, `app_settings` and `documents.default_cert`.

Other CLI commands: `flask db reset`, `flask db drop`, `flask db upgrade`.

## Running

Development:
```bash
flask run
```

Production (example with gunicorn behind nginx):
```bash
gunicorn -w 2 -b 127.0.0.1:5000 "app:app"
```

If deployed at a sub-path (e.g. `/abbreviarium/`), configure nginx with `proxy_set_header X-Forwarded-Prefix /abbreviarium;` — the app reads this via `ProxyFix`.

## Testing

```bash
PYTHONPATH=. pytest tests/ -v
```

Tests use an in-memory SQLite database and do not require a running server.

## Access control model

| Role | How granted | Scope |
|---|---|---|
| Creator | Creates the project / document | Full access |
| Project member | Admin adds via project settings | All documents and pages in the project |
| Document member | Admin adds via document settings | That document's pages only |

Unauthenticated requests to protected routes are redirected to `/login`.
