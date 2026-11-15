"""Publish Field Shift: source to a public GitHub repository, site to GitHub Pages.

    python deploy/deploy.py check     # nothing secret is tracked or built into the site
    python deploy/deploy.py source    # create the repository if needed and push `main`
    python deploy/deploy.py site      # build the static site and push it to the `gh-pages` branch
    python deploy/deploy.py pages     # switch GitHub Pages on for that branch
    python deploy/deploy.py all       # the four steps in order
(run from the project root)

GitHub authentication is the machine's git credential helper; no token is stored or printed.
The site is static, so there is no server and no secret to deploy: the two keys in .env are
only used by the data pipeline, and `check` refuses to continue if either value appears in a
tracked file or in the built site.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHUB_USER = "Rohith-Kumar-SS"
REPO = "field-shift"
REMOTE = f"https://github.com/{GITHUB_USER}/{REPO}.git"
SITE_URL = f"https://{GITHUB_USER.lower()}.github.io/{REPO}/"
SITE_DIR = ROOT / "deploy" / ".site"
DIST = ROOT / "frontend" / "dist"
DESCRIPTION = "Field Shift: compare crop rotations for a field with NASA Earth observations (NASA Space Apps 2026)"


def say(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


def git(*args: str, cwd: Path = ROOT, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=quiet)


# ---------------------------------------------------------------- GitHub API
def _token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, check=True).stdout
    tok = dict(line.split("=", 1) for line in out.splitlines() if "=" in line).get("password", "")
    if not tok:
        sys.exit("[deploy] no GitHub credential found in the git credential helper; sign in with git first")
    return tok


def api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {_token()}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "field-shift-deploy", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {}


# ---------------------------------------------------------------- steps
def secrets_in_env() -> list[str]:
    env = ROOT / ".env"
    if not env.exists():
        return []
    vals = []
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            if len(v) >= 12:
                vals.append(v)
    return vals


def check() -> None:
    tracked = git("ls-files", quiet=True).stdout.splitlines()
    bad = [f for f in tracked if Path(f).name == ".env" or f.startswith("data/raw/")]
    if bad:
        sys.exit(f"[deploy] refusing: these must not be tracked: {bad[:5]}")
    for i, value in enumerate(secrets_in_env(), 1):
        hit = subprocess.run(["git", "grep", "-l", "-F", "-e", value], cwd=ROOT, capture_output=True, text=True)
        if hit.stdout.strip():
            sys.exit(f"[deploy] refusing: credential #{i} from .env appears in tracked file(s): {hit.stdout.split()[:3]}")
        if DIST.exists():
            for p in DIST.rglob("*"):
                if p.is_file() and p.suffix in (".js", ".html", ".css", ".json", ".geojson", ".map"):
                    if value in p.read_text(encoding="utf-8", errors="ignore"):
                        sys.exit(f"[deploy] refusing: credential #{i} from .env appears in the built site ({p.name})")
    big = [f for f in tracked if (ROOT / f).exists() and (ROOT / f).stat().st_size > 50_000_000]
    if big:
        sys.exit(f"[deploy] refusing: files over 50 MB are tracked: {big[:3]}")
    say(f"check passed: {len(tracked)} tracked files, no credentials, no oversized files")


def ensure_repo() -> None:
    code, _ = api("GET", f"/repos/{GITHUB_USER}/{REPO}")
    if code == 404:
        code, body = api("POST", "/user/repos", {"name": REPO, "description": DESCRIPTION, "homepage": SITE_URL,
                                                 "private": False, "has_wiki": False})
        if code >= 300:
            sys.exit(f"[deploy] could not create the repository: HTTP {code} {body.get('message', '')}")
        say(f"created github.com/{GITHUB_USER}/{REPO} (public)")
    elif code >= 300:
        sys.exit(f"[deploy] GitHub answered HTTP {code} for the repository")


def source() -> None:
    ensure_repo()
    if git("status", "--porcelain", quiet=True).stdout.strip():
        sys.exit("[deploy] commit your changes first: the working tree is not clean")
    if "origin" not in git("remote", quiet=True).stdout.split():
        git("remote", "add", "origin", REMOTE)
    else:
        git("remote", "set-url", "origin", REMOTE)
    git("push", "-u", "origin", "main")
    say(f"source pushed: https://github.com/{GITHUB_USER}/{REPO}")


def site() -> None:
    ensure_repo()
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    check()
    if not (SITE_DIR / ".git").exists():
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        git("init", "-q", "-b", "gh-pages", cwd=SITE_DIR)
        git("config", "core.autocrlf", "false", cwd=SITE_DIR)
        git("remote", "add", "origin", REMOTE, cwd=SITE_DIR)
    for item in SITE_DIR.iterdir():
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(DIST, SITE_DIR, dirs_exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (SITE_DIR / "404.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=/{REPO}/">'
        f'<title>Field Shift</title><a href="/{REPO}/">Field Shift</a>', encoding="utf-8")
    git("add", "-A", cwd=SITE_DIR)
    if git("diff", "--cached", "--quiet", cwd=SITE_DIR, check=False).returncode == 0:
        say("site unchanged")
    else:
        head = git("rev-parse", "--short", "HEAD", quiet=True).stdout.strip()
        git("commit", "-q", "-m", f"Site built from {head}", cwd=SITE_DIR)
    git("push", "-f", "-u", "origin", "gh-pages", cwd=SITE_DIR)
    size = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file()) / 1e6
    say(f"site pushed to the gh-pages branch ({size:.0f} MB)")


def pages() -> None:
    code, body = api("GET", f"/repos/{GITHUB_USER}/{REPO}/pages")
    want = {"source": {"branch": "gh-pages", "path": "/"}}
    if code == 404:
        code, body = api("POST", f"/repos/{GITHUB_USER}/{REPO}/pages", want)
        if code >= 300:
            sys.exit(f"[deploy] could not switch GitHub Pages on: HTTP {code} {body.get('message', '')}")
        say("GitHub Pages switched on")
    elif body.get("source", {}).get("branch") != "gh-pages":
        api("PUT", f"/repos/{GITHUB_USER}/{REPO}/pages", want)
        say("GitHub Pages pointed at gh-pages")
    api("PATCH", f"/repos/{GITHUB_USER}/{REPO}", {"homepage": SITE_URL, "description": DESCRIPTION})
    say(f"website: {SITE_URL}")


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "help"
    steps = {"check": check, "source": source, "site": site, "pages": pages}
    if step == "all":
        for fn in (check, source, site, pages):
            fn()
    elif step in steps:
        steps[step]()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
