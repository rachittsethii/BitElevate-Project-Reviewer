"""Turn a GitHub URL (or a local folder) into a bounded RepoSnapshot.

Context budget matters: we never send a whole repo to the LLM. We prioritise
README > manifests > tests > largest/central source files, capped by characters.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path, PurePosixPath

import requests

from .models import RepoSnapshot

MAX_FILES = 12
MAX_CHARS_PER_FILE = 5_000
MAX_TOTAL_CHARS = 30_000
MAX_TREE_PATHS = 2_000

SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "dist", "build", "__pycache__", ".next", "vendor", "target"}
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".lock", ".min.js",
    ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".pyc", ".so", ".exe", ".bin", ".csv", ".parquet",
}
CODE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".cpp", ".c", ".cs", ".php", ".rb", ".kt", ".swift"}
MANIFEST_NAMES = {
    "requirements.txt", "pyproject.toml", "package.json", "pom.xml", "go.mod", "Cargo.toml", "Dockerfile",
}


class RepoError(Exception):
    """User-facing problem (bad URL, private repo, rate limit)."""


def parse_github_url(url: str) -> tuple[str, str]:
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:$|/tree/|/blob/)", url.strip())
    if not m:
        raise RepoError("Enter a URL like https://github.com/owner/repo")
    return m.group(1), m.group(2)


def _skip(path: str) -> bool:
    p = PurePosixPath(path)
    if any(part in SKIP_DIRS for part in p.parts):
        return True
    return p.suffix.lower() in SKIP_SUFFIXES


def _priority(path: str) -> tuple[int, int]:
    """Lower sorts first. Second element prefers shallower paths."""
    p = PurePosixPath(path)
    name = p.name.lower()
    depth = len(p.parts)
    if name.startswith("readme"):
        rank = 0
    elif p.name in MANIFEST_NAMES:
        rank = 1
    elif any(seg in ("tests", "test", "__tests__") for seg in p.parts[:-1]) or name.startswith("test_"):
        rank = 3
    elif name in ("main.py", "app.py", "index.js", "index.ts", "server.js", "main.go"):
        rank = 2
    elif p.suffix.lower() in CODE_SUFFIXES:
        rank = 4
    else:
        rank = 9
    return rank, depth


def select_files(paths: list[str]) -> list[str]:
    candidates = [p for p in paths if not _skip(p)]
    candidates.sort(key=_priority)
    # keep at most 2 test files so tests don't crowd out source
    chosen, tests = [], 0
    for p in candidates:
        is_test = _priority(p)[0] == 3
        if is_test and tests >= 2:
            continue
        tests += is_test
        if _priority(p)[0] == 9 and not p.lower().endswith((".md", ".yml", ".yaml", ".toml", ".cfg", ".txt", ".ini")):
            continue
        chosen.append(p)
        if len(chosen) >= MAX_FILES:
            break
    return chosen


def _budget(files: dict[str, str]) -> tuple[dict[str, str], bool]:
    out, total, cut = {}, 0, False
    for path, text in files.items():
        if len(text) > MAX_CHARS_PER_FILE:
            text, cut = text[:MAX_CHARS_PER_FILE] + "\n...[truncated]", True
        if total + len(text) > MAX_TOTAL_CHARS:
            cut = True
            break
        out[path] = text
        total += len(text)
    return out, cut


def from_github(url: str, token: str | None = None, timeout: int = 20) -> RepoSnapshot:
    owner, repo = parse_github_url(url)
    token = token or os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "bitelevate-reviewer"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base = f"https://api.github.com/repos/{owner}/{repo}"

    meta = requests.get(base, headers=headers, timeout=timeout)
    if meta.status_code == 404:
        raise RepoError("Repo not found or private. Only public repos are supported.")
    if meta.status_code in (403, 429):
        raise RepoError("GitHub rate limit hit. Set GITHUB_TOKEN in .env to raise the limit.")
    meta.raise_for_status()
    branch = meta.json().get("default_branch", "main")

    tree = requests.get(f"{base}/git/trees/{branch}?recursive=1", headers=headers, timeout=timeout)
    tree.raise_for_status()
    tree_json = tree.json()
    paths = [e["path"] for e in tree_json.get("tree", []) if e["type"] == "blob"]
    truncated = bool(tree_json.get("truncated")) or len(paths) > MAX_TREE_PATHS
    paths = paths[:MAX_TREE_PATHS]

    raw: dict[str, str] = {}
    for path in select_files(paths):
        r = requests.get(f"{base}/contents/{path}?ref={branch}", headers=headers, timeout=timeout)
        if r.status_code != 200:
            continue
        data = r.json()
        if data.get("encoding") == "base64" and data.get("size", 0) < 200_000:
            try:
                raw[path] = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            except Exception:
                continue
    files, cut = _budget(raw)
    return RepoSnapshot(name=f"{owner}/{repo}", source=url, paths=paths, files=files, truncated=truncated or cut)


def from_local(folder: str) -> RepoSnapshot:
    """Same snapshot from a local folder -- used for tests, offline demos, and zip uploads."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise RepoError(f"Not a folder: {folder}")
    paths = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if not any(part in SKIP_DIRS for part in PurePosixPath(rel).parts):
                paths.append(rel)
    paths = sorted(paths)[:MAX_TREE_PATHS]
    raw = {}
    for path in select_files(paths):
        try:
            raw[path] = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    files, cut = _budget(raw)
    return RepoSnapshot(name=root.name, source=str(root), paths=paths, files=files, truncated=cut)
