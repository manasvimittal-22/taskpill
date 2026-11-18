"""Asking GitHub for the latest TaskPill release, and downloading its installer.

What's sent: a plain HTTPS GET to GitHub's public API with a ``TaskPill/<version>``
User-Agent. Nothing about the user or their sessions. Downloads only come from
GitHub's own hosts, and only the installer file of that release.
"""

from __future__ import annotations

import json
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from taskpill import __repo__, __version__
from taskpill.domain.updates import Release, parse_version

API = f"https://api.github.com/repos/{__repo__}/releases/latest"
TIMEOUT = 8
MAX_INSTALLER = 200 * 1024 * 1024  # bigger than any real installer: refuse
TRUSTED_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class UpdateError(Exception):
    """Couldn't check or download; the message is shown as is."""


def _get(url: str, accept: str) -> urllib.request.Request:
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in TRUSTED_HOSTS:
        raise UpdateError("The update link isn't from GitHub, so it was skipped.")
    return urllib.request.Request(url, headers={
        "User-Agent": f"TaskPill/{__version__}",
        "Accept": accept,
    })


def parse_release(data: object) -> Release | None:
    """The latest release from GitHub's JSON, or None if it isn't usable."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    page = data.get("html_url")
    if not isinstance(tag, str) or parse_version(tag) is None or not isinstance(page, str):
        return None
    installer, size = None, 0
    for asset in data.get("assets") or []:
        name = asset.get("name") if isinstance(asset, dict) else None
        url = asset.get("browser_download_url") if isinstance(asset, dict) else None
        if isinstance(name, str) and name.startswith("TaskPill-Setup-") and \
                name.endswith(".exe") and isinstance(url, str):
            installer, size = url, int(asset.get("size") or 0)
            break
    return Release(tag.lstrip("v"), page, installer, size)


def fetch_latest() -> Release | None:
    """Ask GitHub. Raises UpdateError when offline or GitHub says no."""
    try:
        with urllib.request.urlopen(_get(API, "application/vnd.github+json"),
                                    timeout=TIMEOUT) as response:
            return parse_release(json.loads(response.read(1024 * 1024)))
    except UpdateError:
        raise
    except Exception as e:  # offline, rate-limited, no release yet (404), bad JSON
        raise UpdateError("Couldn't reach GitHub to check for updates.") from e


def download_installer(release: Release, folder: Path | None = None) -> Path:
    """Download the release's installer into a temp folder; returns its path."""
    if release.installer_url is None:
        raise UpdateError("This release has no installer to download.")
    if release.installer_size > MAX_INSTALLER:
        raise UpdateError("The installer is unexpectedly large, so it wasn't downloaded.")
    target = (folder or Path(tempfile.gettempdir())) / f"TaskPill-Setup-{release.version}.exe"
    try:
        with urllib.request.urlopen(_get(release.installer_url, "application/octet-stream"),
                                    timeout=60) as response:
            if urlparse(response.geturl()).hostname not in TRUSTED_HOSTS:
                raise UpdateError("The download was redirected away from GitHub.")
            written = 0
            with open(target, "wb") as out:
                while chunk := response.read(256 * 1024):
                    written += len(chunk)
                    if written > MAX_INSTALLER:
                        raise UpdateError("The download was unexpectedly large.")
                    out.write(chunk)
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    except Exception as e:
        target.unlink(missing_ok=True)
        raise UpdateError("The download didn't finish. Try again later.") from e
    return target
