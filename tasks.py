"""Cross-platform task runner (the Makefile forwards to this).

    python tasks.py setup    install Python and Node dependencies
    python tasks.py data     run the data pipeline (cached; safe to re-run)
                             data --region all | data --region punjab_sangrur | data --region all export
    python tasks.py dev      start the web app on http://localhost:5180
    python tasks.py test     run the tests (Python engine, pipeline maths, browser-engine parity)
    python tasks.py build    build the static site into frontend/dist
    python tasks.py serve    serve the built site on http://localhost:5180
    python tasks.py docs     regenerate DATA_LOG.md and ROTATION_KNOWLEDGE.md
    python tasks.py deploy   publish to GitHub (source) and GitHub Pages (site)
    python tasks.py check    check credentials and data services (prints no secrets)

The app is a static site: there is no server to run. `data ... export` writes everything the
browser needs into frontend/public/data, and the scoring runs in the browser.
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
WEB_PORT = 5180


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> int:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, shell=(os.name == "nt" and cmd[0] in ("npm", "npx"))).returncode


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


def docs() -> None:
    run([python(), "-m", "pipeline.data_log"])
    run([python(), "-m", "engine.knowledge_doc"])


def test() -> None:
    run([python(), "-m", "pytest", "tests", "-q"])
    if shutil.which("npm") and (FRONTEND / "node_modules").exists():
        run(["npx", "tsc", "--noEmit"], cwd=FRONTEND)


def build() -> None:
    run(["npm", "run", "build"], cwd=FRONTEND)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "setup":
        setup()
    elif cmd == "data":
        data(sys.argv[2:])
    elif cmd == "dev":
        print(f"\nApp  http://localhost:{WEB_PORT}   (Ctrl+C stops it)\n")
        run(["npm", "run", "dev"], cwd=FRONTEND, check=False)
    elif cmd == "test":
        test()
    elif cmd == "build":
        build()
    elif cmd == "serve":
        if not (FRONTEND / "dist").exists():
            build()
        run(["npm", "run", "preview"], cwd=FRONTEND, check=False)
    elif cmd == "docs":
        docs()
    elif cmd == "deploy":
        run([python(), "deploy/deploy.py", *(sys.argv[2:] or ["all"])])
    elif cmd == "check":
        run([python(), "-m", "pipeline.check_access"])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
