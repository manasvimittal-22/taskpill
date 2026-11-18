"""The public export (Phase 9): only the app goes public, never secrets or notes."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publish_public",
                                              ROOT / "packaging" / "publish_public.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


def test_private_blocks_are_removed():
    text = ("keep\n  # private:start (why)\n  secret job\n  # private:end\nkeep too\n"
            "Status.<!-- private:start --> See plan.md.<!-- private:end --> Done.\n")
    out = pub.strip_private(text)
    assert "secret job" not in out and "plan.md" not in out
    assert out == "keep\nkeep too\nStatus. Done.\n"


def test_the_scan_finds_secrets_and_personal_details():
    bad = "\n".join([
        'token = "ghp_' + "a" * 36 + '"',
        "key AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----",
        'password = "hunter2hunter2"',
        "mail me at someone" + "@gmail.com",
        "C:" + "\\Users\\alice\\project",
    ])
    kinds = {f.split(": ", 1)[1] for f in pub.scan("x.py", bad)}
    assert kinds == {"GitHub token", "AWS key", "private key", "API key assignment",
                     "personal email", "local user path"}


def test_explicit_exceptions_and_safe_text_pass():
    ok = "\n".join([
        'TOKEN = "fake-token-0123456789"  # publish-scan: ok (a fake test token)',
        "51945431+someone@users.noreply.github.com",  # noreply addresses are meant to be public
        "%APPDATA%\\TaskPill and C:\\Users\\<you>\\.claude",
    ])
    assert pub.scan("x.py", ok) == []


def test_the_export_holds_only_the_app():
    export, findings = pub.build_export()
    assert findings == []
    names = set(export)
    for must in ("README.md", "LICENSE", "SECURITY.md", "src/taskpill/app.py",
                 "hook/taskpill_hook.py", "packaging/taskpill.spec"):
        assert must in names
    for never in ("CLAUDE.md", "plan.md", "docs/worklog.md", "docs/design.md",
                  "docs/manual-checks.md", ".claude/settings.json",
                  "tests/test_vscode_contract.py"):
        assert never not in names
    assert not any(n.startswith(("vscode-extension/", "src/taskpill.egg-info")) for n in names)
    readme = export["README.md"].decode("utf-8")
    assert "plan.md" not in readme and "CLAUDE.md" not in readme
    ci = export[".github/workflows/ci.yml"].decode("utf-8")
    assert "vscode-extension" not in ci


def test_it_never_writes_inside_this_repo(capsys):
    assert pub.main([str(ROOT / "public-copy")]) == 2


def test_every_exported_python_file_still_compiles():
    """Bug (2026-11-17): stripping private markers inside code broke the exporter and
    its test in the first public commit; the public CI caught it."""
    export, _ = pub.build_export()
    for rel, data in export.items():
        if rel.endswith((".py", ".spec")):
            compile(data.decode("utf-8"), rel, "exec")
    # and the exporter's own marker handling survives the export intact
    assert b"PRIVATE_BLOCK = re.compile(" in export["packaging/publish_public.py"]
