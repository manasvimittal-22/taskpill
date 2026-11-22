"""Copy the app (and only the app) into the public repo (Phase 9).

    python packaging/publish_public.py <public repo folder> [--check]

This private repo is the workshop; the public repo (manasvimittal-22/taskpill)
gets a clean copy with its own history:

1. Only the files in ``INCLUDE`` are copied. Plans, notes, CLAUDE.md, the
   worklog and the on-hold VS Code extension never leave this repo.
2. Inside copied text files, anything between ``private:start`` and
   ``private:end`` markers is removed (e.g. README links to internal docs).
3. Everything that would be published is scanned for secrets and personal
   details first. One finding stops the whole run, and nothing is written.
4. Files in the public folder that are no longer in the export are deleted
   (except its ``.git``), so the public repo mirrors the export exactly.

``--check`` only scans and lists what would be published.
Committing and pushing are separate steps (see CLAUDE.md → Commands).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What the public repo contains (paths relative to the repo root; folders recurse).
INCLUDE = [
    "README.md", "LICENSE", "SECURITY.md", "pyproject.toml", ".gitignore", ".gitattributes",
    ".github/workflows/ci.yml", ".github/workflows/release.yml",
    "src", "hook", "tests",
    "docs/images",
    "packaging/make_icon.py", "packaging/make_sounds.py", "packaging/make_readme_images.py",
    "packaging/make_portable.py", "packaging/entry_app.py", "packaging/taskpill.spec",
    "packaging/installer.iss", "packaging/build_windows.ps1", "packaging/portable.txt",
    "packaging/taskpill_mac.spec", "packaging/build_macos.sh",
    "packaging/taskpill.ico", "packaging/taskpill.png", "packaging/publish_public.py",
]
# Never published, even if inside an included folder.
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".venv"}
EXCLUDE_FILES = {"tests/test_vscode_contract.py"}  # tests the on-hold extension
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".iss", ".ps1", ".txt", ".spec",
                 ".gitignore", ".gitattributes", ""}

MARKED_SUFFIXES = {".md", ".yml", ".yaml"}  # where private markers may appear
PRIVATE_BLOCK = re.compile(r"[^\n]*private:start.*?private:end[^\n]*\n?", re.S)
INLINE_PRIVATE = re.compile(r"<!-- private:start -->.*?<!-- private:end -->", re.S)

# What must never be published. Each finding names the file and line.
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "API key assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
    "personal email": re.compile(r"[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo|icloud)\.com",
                                 re.I),
    "local user path": re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!<|you\b|name\b)[A-Za-z0-9._-]+"),
}
# Hits that are fine: the patterns themselves (in this file and its tests).
ALLOWED_FILES = {"packaging/publish_public.py", "tests/test_publish_public.py"}


def tracked() -> set[str]:
    """Files git tracks here: build leftovers (egg-info, dist, caches) never ship."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return {name for name in out.stdout.decode("utf-8").split(chr(0)) if name}


def collect() -> list[Path]:
    files: list[Path] = []
    in_git = tracked()
    for entry in INCLUDE:
        path = ROOT / entry
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for p in candidates:
            rel = p.relative_to(ROOT).as_posix()
            if EXCLUDE_PARTS & set(Path(rel).parts) or rel in EXCLUDE_FILES or rel not in in_git:
                continue
            files.append(p)
    return files


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {".gitignore", ".gitattributes"}


def strip_private(text: str) -> str:
    text = INLINE_PRIVATE.sub("", text)
    return PRIVATE_BLOCK.sub("", text)


def scan(rel: str, text: str) -> list[str]:
    if rel in ALLOWED_FILES:
        return []
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        if "publish-scan: ok" in line:  # an explicit, visible exception (e.g. a test fake)
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{rel}:{i}: {name}")
    return findings


def build_export() -> tuple[dict[str, bytes], list[str]]:
    """Every file to publish (relative path → bytes), and any scan findings."""
    export: dict[str, bytes] = {}
    findings: list[str] = []
    for path in collect():
        rel = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        if is_text(path):
            text = data.decode("utf-8")
            # Markers are only used in docs and CI files. Never strip code: this very
            # file and its test mention the markers, and stripping them broke both
            # in the first public commit (caught by the public CI, 2026-11-17).
            if path.suffix.lower() in MARKED_SUFFIXES:
                text = strip_private(text).rstrip() + "\n"  # no blank tail (\r\n too)
            findings += scan(rel, text)
            data = text.encode("utf-8")
        export[rel] = data
    return export, findings


def write(export: dict[str, bytes], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for old in sorted(target.rglob("*"), reverse=True):
        rel = old.relative_to(target).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if old.is_file() and rel not in export:
            old.unlink()
        elif old.is_dir() and not any(old.iterdir()):
            old.rmdir()
    for rel, data in export.items():
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.read_bytes() != data:
            out.write_bytes(data)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    export, findings = build_export()
    if findings:
        print("Stopped: these must not be published:")
        print("\n".join(f"  {f}" for f in findings))
        return 1
    if "--check" in argv:
        print("\n".join(sorted(export)))
        print(f"{len(export)} files, scan clean.")
        return 0
    target = Path(argv[0]).resolve()
    if target == ROOT or ROOT in target.parents:
        print("The public folder must be outside this repo.")
        return 2
    write(export, target)
    print(f"Exported {len(export)} files to {target} (scan clean).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
