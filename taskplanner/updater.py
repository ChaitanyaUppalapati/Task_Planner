"""In-app updates from GitHub Releases.

Flow: query the latest release -> if newer, download the installer asset ->
verify it against the release's SHA256SUMS.txt -> run it silently (it closes
this app, installs in place and relaunches it). User data in %APPDATA% is untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskplanner import __version__

API = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = f"TaskPlanner-Updater/{__version__}"
INSTALLER_RE = re.compile(r"^TaskPlannerSetup-.*\.exe$", re.I)
TIMEOUT = 30


class UpdateError(Exception):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    html_url: str
    installer_name: str
    installer_url: str          # browser download URL
    installer_api_url: str      # API asset URL (works with a token for private repos)
    sums_url: str | None
    sums_api_url: str | None


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _request(url: str, token: str = "", accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    if token:
        # Unredirected: asset downloads redirect to storage that rejects extra auth.
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def fetch_latest(repo: str, token: str = "") -> ReleaseInfo:
    try:
        with urllib.request.urlopen(_request(API.format(repo=repo), token), timeout=TIMEOUT) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("No published release found (or the repository is private — "
                              "add a GitHub token in Settings).") from e
        if e.code == 403:
            raise UpdateError("GitHub rate limit reached. Try again later.") from e
        raise UpdateError(f"GitHub returned HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"Could not reach GitHub: {e}") from e
    return parse_release(data)


def parse_release(data: dict) -> ReleaseInfo:
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") or []
    installer = next((a for a in assets if INSTALLER_RE.match(a.get("name", ""))), None)
    if installer is None:
        raise UpdateError(f"Release {tag} has no installer attached.")
    sums = next((a for a in assets if a.get("name", "").upper() == "SHA256SUMS.TXT"), None)
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or ""),
        installer_name=installer["name"],
        installer_url=installer.get("browser_download_url", ""),
        installer_api_url=installer.get("url", ""),
        sums_url=sums.get("browser_download_url") if sums else None,
        sums_api_url=sums.get("url") if sums else None,
    )


def _download(url: str, api_url: str | None, dest: Path, token: str,
              progress: Callable[[int, int], None] | None = None) -> None:
    if token and api_url:
        req = _request(api_url, token, accept="application/octet-stream")
    else:
        req = _request(url, accept="application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"Download failed: {e}") from e


def expected_hash(sums_text: str, filename: str) -> str | None:
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_installer(info: ReleaseInfo, token: str = "",
                       progress: Callable[[int, int], None] | None = None,
                       folder: Path | None = None) -> Path:
    """Download and verify the installer. Returns its path."""
    folder = folder or Path(tempfile.mkdtemp(prefix="taskplanner-update-"))
    dest = folder / info.installer_name
    _download(info.installer_url, info.installer_api_url, dest, token, progress)
    if info.sums_url:
        sums_path = folder / "SHA256SUMS.txt"
        _download(info.sums_url, info.sums_api_url, sums_path, token)
        want = expected_hash(sums_path.read_text(encoding="utf-8", errors="replace"),
                             info.installer_name)
        if want is None:
            raise UpdateError("Checksum file does not list the installer.")
        if sha256_of(dest) != want:
            dest.unlink(missing_ok=True)
            raise UpdateError("Downloaded installer failed the integrity check; not installed.")
    if dest.stat().st_size < 1_000_000:
        raise UpdateError("Downloaded installer is unexpectedly small; not installed.")
    return dest


def launch_installer(path: Path) -> None:
    """Run the installer silently; it replaces the app and relaunches it."""
    if sys.platform != "win32":
        raise UpdateError("Automatic installation is only supported on Windows.")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
         "/SP-"],
        creationflags=flags, close_fds=True, cwd=os.path.dirname(path),
    )
