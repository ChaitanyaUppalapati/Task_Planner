import hashlib

import pytest

from taskplanner import updater


def test_version_compare():
    assert updater.is_newer("1.1.0", "1.0.0")
    assert updater.is_newer("v1.10.0".lstrip("v"), "1.9.3")
    assert updater.is_newer("2.0", "1.9.9")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("1.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0")


def release_json(**over):
    data = {
        "tag_name": "v9.9.9", "body": "notes", "html_url": "https://example/rel",
        "assets": [
            {"name": "TaskPlannerSetup-9.9.9.exe", "browser_download_url": "B1", "url": "A1"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "B2", "url": "A2"},
        ],
    }
    data.update(over)
    return data


def test_parse_release():
    info = updater.parse_release(release_json())
    assert info.version == "9.9.9" and info.installer_url == "B1" and info.sums_url == "B2"
    with pytest.raises(updater.UpdateError):
        updater.parse_release(release_json(assets=[]))


def test_expected_hash():
    text = "ABC123  TaskPlannerSetup-1.exe\nDEF  TaskPlanner.exe\n"
    assert updater.expected_hash(text, "TaskPlannerSetup-1.exe") == "abc123"
    assert updater.expected_hash(text, "missing.exe") is None


def _local_release(tmp_path, payload: bytes, listed_hash: str | None = None):
    src = tmp_path / "src"
    src.mkdir()
    exe = src / "TaskPlannerSetup-9.9.9.exe"
    exe.write_bytes(payload)
    digest = listed_hash or hashlib.sha256(payload).hexdigest().upper()
    sums = src / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  TaskPlannerSetup-9.9.9.exe\n")
    return updater.ReleaseInfo("9.9.9", "v9.9.9", "", "", exe.name, exe.as_uri(), "",
                               sums.as_uri(), None)


def test_download_and_verify(tmp_path):
    payload = b"x" * 1_200_000
    info = _local_release(tmp_path, payload)
    seen = []
    out = tmp_path / "out"
    out.mkdir()
    path = updater.download_installer(info, progress=lambda d, t: seen.append(d), folder=out)
    assert path.read_bytes() == payload and seen[-1] == len(payload)


def test_tampered_download_is_rejected(tmp_path):
    info = _local_release(tmp_path, b"x" * 1_200_000, listed_hash="00" * 32)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(updater.UpdateError, match="integrity"):
        updater.download_installer(info, folder=out)
    assert not (out / "TaskPlannerSetup-9.9.9.exe").exists()


def test_fetch_latest_maps_404(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "nf", {}, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(updater.UpdateError, match="No published release"):
        updater.fetch_latest("a/b")
