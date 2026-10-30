"""Cheap, deterministic checks. They run BEFORE the LLM and are shown to it as facts,
so the model spends its tokens on judgement, not on counting files."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

from .models import RepoSnapshot

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic_api_key": re.compile(
        r"""(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]"""
    ),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "JavaScript",
    ".tsx": "TypeScript", ".java": "Java", ".go": "Go", ".rs": "Rust", ".cpp": "C++",
    ".c": "C", ".cs": "C#", ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift",
    ".ipynb": "Jupyter",
}
MANIFESTS = {
    "requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "package.json",
    "pom.xml", "build.gradle", "go.mod", "Cargo.toml", "composer.json", "Gemfile",
}


def _is_test_path(p: str) -> bool:
    parts = PurePosixPath(p.lower()).parts
    name = parts[-1]
    return (
        any(seg in ("tests", "test", "__tests__", "spec") for seg in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts", "_test.go"))
    )


def compute_signals(snap: RepoSnapshot) -> dict:
    paths = snap.paths
    lower = [p.lower() for p in paths]
    names = [PurePosixPath(p).name for p in paths]

    readme = next((p for p in paths if PurePosixPath(p).name.lower().startswith("readme")), None)
    readme_text = snap.files.get(readme, "") if readme else ""

    langs = Counter(
        LANG_BY_EXT[PurePosixPath(p).suffix.lower()]
        for p in paths
        if PurePosixPath(p).suffix.lower() in LANG_BY_EXT
    )

    secrets_found: list[str] = []
    for path, text in snap.files.items():
        for label, pat in SECRET_PATTERNS.items():
            if pat.search(text):
                secrets_found.append(f"{path} ({label})")
    committed_env = [p for p in paths if PurePosixPath(p).name in (".env", ".env.local", ".env.production")]

    test_files = [p for p in paths if _is_test_path(p)]
    code_files = [p for p in paths if PurePosixPath(p).suffix.lower() in LANG_BY_EXT and not _is_test_path(p)]

    return {
        "file_count": len(paths),
        "languages": dict(langs.most_common(4)),
        "has_readme": bool(readme),
        "readme_chars": len(readme_text),
        "readme_has_setup": bool(re.search(r"(?i)\b(install|setup|getting started|usage|run)\b", readme_text)),
        "has_tests": bool(test_files),
        "test_file_count": len(test_files),
        "test_to_code_ratio": round(len(test_files) / max(len(code_files), 1), 2),
        "has_ci": any(p.startswith(".github/workflows/") or p in (".gitlab-ci.yml", ".travis.yml") for p in lower),
        "has_license": any(PurePosixPath(p).name.lower().startswith("license") for p in paths),
        "has_gitignore": ".gitignore" in names,
        "has_dependency_manifest": any(n in MANIFESTS for n in names),
        "has_env_example": any(n.startswith(".env") and "example" in n for n in names),
        "committed_env_files": committed_env,
        "possible_secrets": secrets_found,
        "tree_truncated": snap.truncated,
    }


def mentor_flags(signals: dict) -> list[str]:
    """Hard facts that should always reach a human mentor, whatever the LLM says."""
    flags = []
    if signals["possible_secrets"] or signals["committed_env_files"]:
        flags.append("Possible committed secrets / .env file -- verify and rotate keys.")
    if signals["file_count"] < 3:
        flags.append("Repo is almost empty -- may be the wrong link or a placeholder.")
    if not signals["languages"]:
        flags.append("No recognised source files -- review is low-confidence.")
    return flags
