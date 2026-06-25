#!/usr/bin/env python3
"""Generate a from-scratch deployment for this app: scans the box for CPU/RAM/GPU,
asks a couple of sizing questions, and writes out recommended systemd units + a
.env file under ./deploy/generated/. Nothing is installed or started automatically
unless you pass --apply (and confirm) — review the generated files first.

Usage:
    env/bin/python deploy.py                # scan + ask + generate files (safe, no system changes)
    env/bin/python deploy.py --apply         # also offers to install/enable/start the units (sudo)
    env/bin/python deploy.py --yes ...       # skip confirmation prompts (for scripted/CI use)

This only uses the standard library — no new dependencies, consistent with
the rest of this app's "minimal dependencies" deployment philosophy.
"""
import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
GENERATED_DIR = REPO_ROOT / "deploy" / "generated"


# ── server scanning ──────────────────────────────────────────────────────────

def detect_cpus() -> int:
    return os.cpu_count() or 1


def detect_ram_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except FileNotFoundError:
        pass
    return 0


def detect_gpu() -> str | None:
    """Returns a human-readable 'name, VRAM' string if an NVIDIA GPU is usable, else None."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        out = subprocess.run(
            [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        first_line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else None
        return first_line
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError):
        return None


def detect_python_bin() -> str:
    venv_python = REPO_ROOT / "env" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def detect_gunicorn_bin() -> str:
    venv_gunicorn = REPO_ROOT / "env" / "bin" / "gunicorn"
    return str(venv_gunicorn) if venv_gunicorn.exists() else "gunicorn"


# ── recommendation logic ─────────────────────────────────────────────────────

def recommend(cpus: int, ram_mb: int, gpu: str | None,
              expected_users: int, other_apps: int) -> dict:
    """Divide this box's resources across `other_apps + 1` apps (this one included),
    then size the two processes this app needs: the gunicorn web process (light —
    it never touches the model anymore, see worker.py) and the normalization
    worker (the CPU/RAM-heavy one, since it holds the model in memory)."""
    share = other_apps + 1
    budget_cpus = max(1, cpus // share)
    budget_ram_mb = max(512, ram_mb // share)

    # Web process: cheap per-request (DB + Jinja only), so threads track expected
    # concurrent users rather than CPU count. Keep the single-worker/gthread
    # shape already in production (paramhtrs-2.service) — it's the right model
    # for a SQLite-backed app (one writer at a time anyway).
    gunicorn_threads = max(2, min(expected_users, 16))
    gunicorn_workers = 1

    # Worker process: gets whatever CPU budget is left after the web process'
    # threads aren't actually consuming full cores most of the time, so give
    # it the bulk of this app's CPU budget, minus 1 reserved for the web process.
    worker_torch_threads = max(1, budget_cpus - 1)

    # Quantization recommendation: biggest win on CPU-only boxes or when RAM
    # is tight; on a GPU box the model fits comfortably either way, so it's
    # optional there (still useful if VRAM is constrained, e.g. < 8GB).
    gpu_vram_mb = None
    if gpu:
        try:
            gpu_vram_mb = int(gpu.split(",")[1].strip().split()[0])
        except (IndexError, ValueError):
            gpu_vram_mb = None
    recommend_quantize = (gpu is None) or (gpu_vram_mb is not None and gpu_vram_mb < 8192)

    # Number of worker.py processes: SQLite is single-writer and each worker
    # process holds its own full copy of the model in RAM, so more than 1 is
    # rarely worth it unless there's a lot of spare RAM AND a backlog problem
    # (which a single worker handling chunks sequentially usually isn't, since
    # documents are normalized chunk-by-chunk in the background already).
    num_worker_processes = 1
    if budget_ram_mb > 8192 and budget_cpus >= 8 and expected_users > 20:
        num_worker_processes = 2

    return {
        "budget_cpus": budget_cpus,
        "budget_ram_mb": budget_ram_mb,
        "gunicorn_workers": gunicorn_workers,
        "gunicorn_threads": gunicorn_threads,
        "worker_torch_threads": worker_torch_threads,
        "recommend_quantize": recommend_quantize,
        "num_worker_processes": num_worker_processes,
        "gpu_vram_mb": gpu_vram_mb,
    }


# ── file generation ──────────────────────────────────────────────────────────

WEB_SERVICE_TEMPLATE = """[Unit]
Description=Gunicorn instance to serve {app_name}
After=network.target

[Service]
User={user}
Group=www-data
WorkingDirectory={repo_root}
Environment="PATH={venv_bin}"
EnvironmentFile=-{repo_root}/.env
ExecStart={gunicorn_bin} --workers {gunicorn_workers} --worker-class gthread --threads {gunicorn_threads} --timeout 960 --bind unix:{repo_root}/{app_name}.sock -m 007 wsgi:app --log-syslog --log-level=info --capture-output
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

WORKER_SERVICE_TEMPLATE = """[Unit]
Description={app_name} background normalization worker {index}
After=network.target

[Service]
User={user}
Group=www-data
WorkingDirectory={repo_root}
Environment="PATH={venv_bin}"
Environment="TORCH_NUM_THREADS={worker_torch_threads}"
EnvironmentFile=-{repo_root}/.env
ExecStart={python_bin} worker.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

ENV_TEMPLATE = """# Generated by deploy.py — review before use, then copy to .env
# (existing .env is never overwritten automatically; see deploy/generated/.env.recommended)
DATABASE_URL=sqlite:///{repo_root}/lines.db
SEQ2SEQ_MODEL=comma-project/normalization-byt5-small
MODEL_QUANTIZED_PATH={repo_root}/model-quantized
MAX_CHUNK_BYTES=512
TORCH_NUM_THREADS={web_torch_threads}
"""


def generate_files(app_name: str, rec: dict) -> list[Path]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    user = getpass.getuser()
    venv_bin = str(REPO_ROOT / "env" / "bin")
    python_bin = detect_python_bin()
    gunicorn_bin = detect_gunicorn_bin()

    written = []

    web_path = GENERATED_DIR / f"{app_name}.service"
    web_path.write_text(WEB_SERVICE_TEMPLATE.format(
        app_name=app_name, user=user, repo_root=REPO_ROOT, venv_bin=venv_bin,
        gunicorn_bin=gunicorn_bin, gunicorn_workers=rec["gunicorn_workers"],
        gunicorn_threads=rec["gunicorn_threads"],
    ))
    written.append(web_path)

    for i in range(1, rec["num_worker_processes"] + 1):
        suffix = "" if rec["num_worker_processes"] == 1 else f"-{i}"
        worker_path = GENERATED_DIR / f"{app_name}-worker{suffix}.service"
        worker_path.write_text(WORKER_SERVICE_TEMPLATE.format(
            app_name=app_name, index=i, user=user, repo_root=REPO_ROOT,
            venv_bin=venv_bin, python_bin=python_bin,
            worker_torch_threads=rec["worker_torch_threads"],
        ))
        written.append(worker_path)

    env_path = GENERATED_DIR / ".env.recommended"
    env_path.write_text(ENV_TEMPLATE.format(
        repo_root=REPO_ROOT, web_torch_threads=max(1, rec["budget_cpus"] - rec["worker_torch_threads"]),
    ))
    written.append(env_path)

    return written


# ── interactive flow ──────────────────────────────────────────────────────────

def ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  Not a number, using default {default}.")
        return default


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                         help="After generating files, offer to install/enable/start them via sudo.")
    parser.add_argument("--yes", action="store_true",
                         help="Skip confirmation prompts (still requires --apply to touch the system).")
    parser.add_argument("--app-name", default="paramhtrs-extension",
                         help="Base name for the systemd units (default: paramhtrs-extension).")
    parser.add_argument("--users", type=int, default=None,
                         help="Expected simultaneous users (skips the interactive prompt).")
    parser.add_argument("--other-apps", type=int, default=None,
                         help="Number of other apps already running on this box (skips the prompt).")
    args = parser.parse_args()

    print("== Scanning this server ==")
    cpus = detect_cpus()
    ram_mb = detect_ram_mb()
    gpu = detect_gpu()
    print(f"  CPUs:   {cpus}")
    print(f"  RAM:    {ram_mb} MB ({ram_mb / 1024:.1f} GB)")
    print(f"  GPU:    {gpu or 'none detected (CPU-only inference)'}")

    print()
    print("== Sizing questions ==")
    expected_users = args.users if args.users is not None else \
        ask_int("Expected number of simultaneous users", 5)
    other_apps = args.other_apps if args.other_apps is not None else \
        ask_int("Number of OTHER apps/services already running on this box", 0)

    rec = recommend(cpus, ram_mb, gpu, expected_users, other_apps)

    print()
    print("== Recommendations ==")
    print(f"  Resource budget for this app: {rec['budget_cpus']} CPUs, {rec['budget_ram_mb']} MB RAM")
    print(f"  gunicorn:        --workers {rec['gunicorn_workers']} --worker-class gthread --threads {rec['gunicorn_threads']}")
    print(f"  worker.py:       {rec['num_worker_processes']} process(es), TORCH_NUM_THREADS={rec['worker_torch_threads']}")
    print(f"  Quantize model:  {'yes — run `flask quantize` (recommended)' if rec['recommend_quantize'] else 'optional — GPU has enough VRAM'}")
    if gpu and rec["gpu_vram_mb"]:
        print(f"                   (detected ~{rec['gpu_vram_mb']} MB VRAM)")

    print()
    print("== Generating files ==")
    written = generate_files(args.app_name, rec)
    for p in written:
        print(f"  wrote {p.relative_to(REPO_ROOT)}")

    print()
    print("Next steps (review the generated files first):")
    print(f"  1. cp {GENERATED_DIR.relative_to(REPO_ROOT)}/.env.recommended .env   # if you don't already have one")
    print("  2. env/bin/pip install -r requirements.txt")
    print("  3. env/bin/flask db upgrade")
    if rec["recommend_quantize"]:
        print("  4. env/bin/flask quantize   # exports + quantizes the model to ./model-quantized")
    print(f"  {5 if rec['recommend_quantize'] else 4}. sudo cp {GENERATED_DIR.relative_to(REPO_ROOT)}/*.service /etc/systemd/system/")
    print("     sudo systemctl daemon-reload")
    print(f"     sudo systemctl enable --now {args.app_name} {args.app_name}-worker*")

    if not args.apply:
        print()
        print("(Run with --apply to have this script offer to run the sudo install/enable/start steps for you.)")
        return

    print()
    if confirm("Install these unit files to /etc/systemd/system and start them now?", args.yes):
        unit_paths = " ".join(str(p) for p in written if p.suffix == ".service")
        subprocess.run(f"sudo cp {unit_paths} /etc/systemd/system/", shell=True, check=True)
        subprocess.run("sudo systemctl daemon-reload", shell=True, check=True)
        unit_names = " ".join(p.stem for p in written if p.suffix == ".service")
        subprocess.run(f"sudo systemctl enable --now {unit_names}", shell=True, check=True)
        print("Installed and started.")
    else:
        print("Skipped. Files are still available under deploy/generated/ for manual install.")


if __name__ == "__main__":
    main()
