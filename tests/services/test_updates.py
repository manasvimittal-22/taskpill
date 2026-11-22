"""Update check (Phase 10). No network: GitHub is faked."""

import io
import json
from pathlib import Path

import pytest

from taskpill.adapters import github_releases as gh
from taskpill.domain.updates import CHECK_EVERY_SECONDS, Release, due, is_newer, parse_version
from taskpill.services.updates import UpdateService, UpdateState

RELEASE_JSON = {
    "tag_name": "v0.2.0",
    "html_url": "https://github.com/manasvimittal-22/taskpill/releases/tag/v0.2.0",
    "draft": False,
    "prerelease": False,
    "assets": [
        {"name": "TaskPill-0.2.0-Windows-Portable.zip", "size": 10,
         "browser_download_url": "https://github.com/x/y/releases/download/v0.2.0/p.zip"},
        {"name": "TaskPill-Setup-0.2.0-Windows.exe", "size": 20_000_000,
         "browser_download_url":
             "https://github.com/manasvimittal-22/taskpill/releases/download/v0.2.0/TaskPill-Setup-0.2.0-Windows.exe"},
    ],
}


# ---- rules --------------------------------------------------------------------------------
def test_versions():
    assert parse_version("v0.2.0") == (0, 2, 0) == parse_version("0.2.0")
    assert parse_version("0.2") is None and parse_version("v1.0.0-beta") is None
    assert is_newer("v0.10.0", "0.9.9")  # numbers, not text
    assert not is_newer("0.1.0", "0.1.0") and not is_newer("0.0.9", "0.1.0")
    assert not is_newer("nonsense", "0.1.0")


def test_at_most_once_a_day():
    assert due(0, 1000)  # never checked
    assert not due(1000, 1000 + CHECK_EVERY_SECONDS - 1)
    assert due(1000, 1000 + CHECK_EVERY_SECONDS)
    assert due(5000, 1000)  # the clock went backwards: check rather than never


# ---- GitHub's reply ---------------------------------------------------------------------------
def test_parse_release_picks_the_installer():
    r = gh.parse_release(RELEASE_JSON)
    assert r.version == "0.2.0"
    assert r.installer_url.endswith("TaskPill-Setup-0.2.0-Windows.exe")
    assert r.installer_size == 20_000_000


@pytest.mark.parametrize("change", [{"draft": True}, {"prerelease": True},
                                    {"tag_name": "latest"}, {"html_url": None}])
def test_unusable_releases_are_ignored(change):
    assert gh.parse_release({**RELEASE_JSON, **change}) is None
    assert gh.parse_release("not a dict") is None


def test_only_github_links_are_followed():
    with pytest.raises(gh.UpdateError):
        gh._get("https://evil.example.com/TaskPill-Setup.exe", "*/*")
    with pytest.raises(gh.UpdateError):
        gh._get("http://github.com/insecure", "*/*")  # not https
    req = gh._get(gh.API, "application/json")
    assert req.get_header("User-agent").startswith("TaskPill/")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_latest(monkeypatch):
    monkeypatch.setattr(gh.urllib.request, "urlopen", lambda req, timeout: FakeResponse(
        json.dumps(RELEASE_JSON).encode(), gh.API))
    assert gh.fetch_latest().version == "0.2.0"


def test_fetch_latest_offline_is_a_readable_error(monkeypatch):
    def offline(req, timeout):
        raise OSError("no network")

    monkeypatch.setattr(gh.urllib.request, "urlopen", offline)
    with pytest.raises(gh.UpdateError, match="Couldn't reach GitHub"):
        gh.fetch_latest()


def test_download_installer(monkeypatch, tmp_path):
    release = gh.parse_release(RELEASE_JSON)
    monkeypatch.setattr(gh.urllib.request, "urlopen", lambda req, timeout: FakeResponse(
        b"MZ installer bytes", "https://objects.githubusercontent.com/x"))
    path = gh.download_installer(release, tmp_path)
    assert path.read_bytes() == b"MZ installer bytes"
    assert path.name == "TaskPill-Setup-0.2.0.exe"


def test_download_redirected_away_from_github_is_refused(monkeypatch, tmp_path):
    release = gh.parse_release(RELEASE_JSON)
    monkeypatch.setattr(gh.urllib.request, "urlopen", lambda req, timeout: FakeResponse(
        b"evil", "https://evil.example.com/x"))
    with pytest.raises(gh.UpdateError, match="redirected"):
        gh.download_installer(release, tmp_path)
    assert not list(tmp_path.iterdir())  # nothing left behind


def test_download_refuses_huge_installers(tmp_path):
    big = Release("0.2.0", "https://github.com/x", "https://github.com/x.exe",
                  gh.MAX_INSTALLER + 1)
    with pytest.raises(gh.UpdateError, match="large"):
        gh.download_installer(big, tmp_path)


# ---- the service ------------------------------------------------------------------------------
def make_service(qtbot, fetch, launched=None, downloaded=None, now=lambda: 10_000_000.0):
    launched = [] if launched is None else launched

    def download(release):
        if downloaded is not None:
            downloaded.append(release.version)
        return Path("C:/tmp/TaskPill-Setup.exe")

    service = UpdateService("0.1.0", fetch, download, launched.append, now,
                            run_in_background=lambda fn: fn())
    statuses = []
    service.changed.connect(statuses.append)
    return service, statuses


def test_finds_a_newer_version_and_announces_it_once(qtbot):
    release = gh.parse_release(RELEASE_JSON)
    service, statuses = make_service(qtbot, lambda: release)
    assert service.check_if_due(last_check=0)
    assert [s.state for s in statuses] == [UpdateState.CHECKING, UpdateState.AVAILABLE]
    assert service.take_announcement() == release
    assert service.take_announcement() is None  # only once


def test_up_to_date_and_not_due(qtbot):
    same = Release("0.1.0", "https://github.com/x", None)
    service, statuses = make_service(qtbot, lambda: same)
    service.check_now()
    assert statuses[-1].state is UpdateState.UP_TO_DATE
    assert not service.check_if_due(last_check=10_000_000.0 - 60)  # checked a minute ago


def test_a_failed_check_says_why(qtbot):
    def offline():
        raise gh.UpdateError("Couldn't reach GitHub to check for updates.")

    service, statuses = make_service(qtbot, offline)
    service.check_now()
    assert statuses[-1].state is UpdateState.FAILED
    assert "Couldn't reach GitHub" in statuses[-1].message


def test_install_downloads_then_runs_the_installer(qtbot):
    release = gh.parse_release(RELEASE_JSON)
    launched, downloaded = [], []
    service, statuses = make_service(qtbot, lambda: release, launched, downloaded)
    service.install()  # nothing available yet: ignored
    assert launched == []
    service.check_now()
    service.install()
    assert downloaded == ["0.2.0"] and launched == [Path("C:/tmp/TaskPill-Setup.exe")]
    assert statuses[-1].state is UpdateState.DOWNLOADING
