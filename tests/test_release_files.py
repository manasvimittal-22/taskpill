"""Release file names: clear per system, and still found by older copies' update check."""

from pathlib import Path

from taskpill.adapters.github_releases import parse_release
from taskpill.release_files import (
    LABELS,
    is_windows_installer,
    mac_dmg,
    windows_installer,
    windows_portable,
)

ROOT = Path(__file__).resolve().parents[1]


def test_each_name_says_its_system():
    assert windows_installer("0.2.1") == "TaskPill-Setup-0.2.1-Windows.exe"
    assert windows_portable("0.2.1") == "TaskPill-0.2.1-Windows-Portable.zip"
    assert mac_dmg("0.2.1") == "TaskPill-0.2.1-Mac-AppleSilicon.dmg"
    assert LABELS["installer"].startswith("Windows")
    assert LABELS["portable"].startswith("Windows")
    assert LABELS["mac"].startswith("Mac")


def old_rule(name: str) -> bool:
    """The exact check in every installed copy from 0.1.0 to 0.2.1."""
    return name.startswith("TaskPill-Setup-") and name.endswith(".exe")


def test_installed_copies_still_find_the_new_installer():
    assert old_rule(windows_installer("0.3.0"))
    assert not old_rule(windows_portable("0.3.0")) and not old_rule(mac_dmg("0.3.0"))


def test_the_new_rule_accepts_old_and_new_names():
    assert is_windows_installer("TaskPill-Setup-0.1.3.exe")
    assert is_windows_installer("TaskPill-Setup-0.2.2-Windows.exe")
    assert not is_windows_installer("TaskPill-0.2.2-Mac-AppleSilicon.dmg")


def test_the_update_check_picks_the_installer_not_the_dmg():
    release = parse_release({
        "tag_name": "v0.3.0", "html_url": "https://github.com/x/y/releases/tag/v0.3.0",
        "assets": [
            {"name": mac_dmg("0.3.0"), "size": 1, "browser_download_url": "https://github.com/a.dmg"},
            {"name": windows_portable("0.3.0"), "size": 1,
             "browser_download_url": "https://github.com/a.zip"},
            {"name": windows_installer("0.3.0"), "size": 1,
             "browser_download_url": "https://github.com/a.exe"},
        ],
    })
    assert release.installer_url == "https://github.com/a.exe"


def test_the_build_scripts_use_the_same_names():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "OutputBaseFilename=TaskPill-Setup-{#AppVersion}-Windows" in iss
    ps1 = (ROOT / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "TaskPill-$version-Windows-Portable.zip" in ps1
    sh = (ROOT / "packaging" / "build_macos.sh").read_text(encoding="utf-8")
    assert 'DMG="dist/TaskPill-$VERSION-Mac-AppleSilicon.dmg"' in sh
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "TaskPill-Setup-*-Windows.exe" in yml and "Windows-Portable.zip" in yml
    assert "Mac-AppleSilicon.dmg" in yml
    for label in LABELS.values():
        assert label in yml
    assert (ROOT / ".github" / "release-notes.md").is_file()
