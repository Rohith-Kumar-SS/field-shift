"""Cross-platform task runner (the Makefile forwards to this).

    python tasks.py setup   install Python and Node dependencies
    python tasks.py data    run the data pipeline (cached; safe to re-run); add --region <id|all>
    python tasks.py dev     start the API (port 8360) and the web app (port 5180)
    python tasks.py test    run the unit tests
    python tasks.py build   build the web app for production
    python tasks.py serve   serve the built app and API together on port 8360
    python tasks.py check   check credentials and data services (prints no secrets)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
FRONTEND = ROOT / "frontend"
API_PORT, WEB_PORT = 8360, 5180


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> int:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, shell=(os.name == "nt" and cmd[0] == "npm")).returncode


def python() -> str:
    return str(PY) if PY.exists() else sys.executable


def setup() -> None:
    if not PY.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    run([str(PY), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    run([str(PY), "-m", "pip", "install", "-r", "requirements.txt", "--quiet"])
    if shutil.which("npm"):
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    else:
        print("npm was not found: install Node.js 18+ to build the web app.")
    if not (ROOT / ".env").exists():
        print("\nNo .env file yet: copy .env.example to .env and add your credentials.")


def data(args: list[str]) -> None:
    """`data` = default region; `data --region all`; `data --region punjab_sangrur smap landsat`."""
    run([python(), "-m", "pipeline.run_all", *args])


def test() -> None:
    run([python(), "-m", "pytest", "tests", "-q"])


def build() -> None:
    run(["npm", "run", "build"], cwd=FRONTEND)


def serve() -> None:
    if not (FRONTEND / "dist").exists():
        build()
    run([python(), "-m", "uvicorn", "backend.main:app", "--port", str(API_PORT)])


def dev() -> None:
    api = subprocess.Popen([python(), "-m", "uvicorn", "backend.main:app", "--port", str(API_PORT), "--reload",
                            "--reload-dir", "backend", "--reload-dir", "engine", "--reload-dir", "knowledge"],
                           cwd=ROOT)
    web = subprocess.Popen("npm run dev" if os.name == "nt" else ["npm", "run", "dev"], cwd=FRONTEND,
                           shell=(os.name == "nt"))
    print(f"\nAPI  http://localhost:{API_PORT}/api/health\nApp  http://localhost:{WEB_PORT}\n(Ctrl+C stops both)\n")
    try:
        web.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in (web, api):
            if p.poll() is None:
                p.terminate()


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "setup":
        setup()
    elif cmd == "data":
        data(sys.argv[2:])
    elif cmd == "dev":
        dev()
    elif cmd == "test":
        test()
    elif cmd == "build":
        build()
    elif cmd == "serve":
        serve()
    elif cmd == "check":
        run([python(), "-m", "pipeline.check_access"])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
