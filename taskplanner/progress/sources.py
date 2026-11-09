"""Automatic progress detectors.

Each detector reads evidence the work leaves on disk and returns a progress
fraction in [0, 1] relative to a baseline captured when the milestone was set up.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from taskplanner.core.models import Milestone, SourceType

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_UNTRACKED_BYTES = 2_000_000
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class SourceError(Exception):
    pass


@dataclass
class Reading:
    progress: float
    evidence: str


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------- git
def _git(repo: str, *args: str, timeout: float = 20) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as e:
        raise SourceError("git is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise SourceError("git timed out") from e
    if proc.returncode != 0:
        raise SourceError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _git_head(repo: str) -> str | None:
    try:
        return _git(repo, "rev-parse", "HEAD").strip()
    except SourceError:
        _git(repo, "rev-parse", "--git-dir")  # raises if not a repository at all
        return None  # repository without commits


_SHORTSTAT = re.compile(r"(\d+) insertions?\(\+\)|(\d+) deletions?\(-\)")


def _lines_changed(repo: str, base: str | None) -> int:
    out = _git(repo, "diff", "--shortstat", base or EMPTY_TREE)
    total = sum(int(a or b) for a, b in _SHORTSTAT.findall(out))
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip())
    for rel in filter(None, untracked):
        p = root / rel
        try:
            if p.stat().st_size <= MAX_UNTRACKED_BYTES:
                with p.open("rb") as fh:
                    total += sum(1 for _ in fh)
        except OSError:
            continue
    return total


class GitSource:
    """config: repo, metric ('commits' | 'lines' | 'message'), target, pattern."""

    def baseline(self, config: dict[str, Any]) -> dict[str, Any]:
        repo = config.get("repo", "")
        if not repo or not Path(repo).exists():
            raise SourceError(f"Repository folder not found: {repo}")
        return {"head": _git_head(repo), "ts": time.time()}

    def read(self, config: dict[str, Any], baseline: dict[str, Any]) -> Reading:
        repo = config.get("repo", "")
        if not repo or not Path(repo).exists():
            raise SourceError(f"Repository folder not found: {repo}")
        base = baseline.get("head")
        metric = config.get("metric", "commits")
        target = max(1.0, float(config.get("target", 1) or 1))
        head = _git_head(repo)
        if metric == "lines":
            n = _lines_changed(repo, base)
            return Reading(_clamp(n / target), f"{n} of {target:.0f} lines changed")
        rev_range = f"{base}..HEAD" if base else "HEAD"
        if head is None:
            return Reading(0.0, "no commits yet")
        if metric == "message":
            pattern = config.get("pattern", "").strip()
            if not pattern:
                raise SourceError("Commit message pattern is empty")
            out = _git(repo, "log", rev_range, "-i", "--fixed-strings", f"--grep={pattern}",
                       "--format=%h %s")
            hits = [ln for ln in out.splitlines() if ln.strip()]
            if hits:
                return Reading(1.0, f"commit found: {hits[0]}")
            return Reading(0.0, f'waiting for a commit mentioning "{pattern}"')
        n = int(_git(repo, "rev-list", "--count", rev_range).strip() or 0)
        return Reading(_clamp(n / target), f"{n} of {target:.0f} commits")


# ----------------------------------------------------------------- documents
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_TAG = re.compile(r"<[^>]+>")
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?")
_LATEX_COMMENT = re.compile(r"(?<!\\)%.*")


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    parts = []
    for para in root.iter(f"{_W_NS}p"):
        parts.append("".join(t.text or "" for t in para.iter(f"{_W_NS}t")))
    return "\n".join(parts)


def _pptx_text(path: Path) -> str:
    parts = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                root = ElementTree.fromstring(z.read(name))
                parts.extend(t.text or "" for t in root.iter(f"{_A_NS}t"))
    return "\n".join(parts)


def _odt_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("content.xml"))
    return " ".join(t for t in root.itertext())


def document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return _docx_text(path)
        if suffix == ".pptx":
            return _pptx_text(path)
        if suffix == ".odt":
            return _odt_text(path)
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise SourceError(f"Cannot read {path.name}: {e}") from e
    if suffix in (".html", ".htm", ".xml"):
        return _TAG.sub(" ", raw)
    if suffix == ".tex":
        raw = _LATEX_COMMENT.sub("", raw)
        return _LATEX_CMD.sub(" ", raw).replace("{", " ").replace("}", " ")
    return raw


def word_count(path: Path) -> int:
    return len(_WORD.findall(document_text(path)))


class DocumentSource:
    """config: path, target_words."""

    def baseline(self, config: dict[str, Any]) -> dict[str, Any]:
        p = Path(config.get("path", ""))
        words = word_count(p) if p.is_file() else 0
        return {"words": words, "ts": time.time()}

    def read(self, config: dict[str, Any], baseline: dict[str, Any]) -> Reading:
        p = Path(config.get("path", ""))
        target = max(1.0, float(config.get("target_words", 500) or 500))
        if not p.is_file():
            return Reading(0.0, f"{p.name or 'document'} not created yet")
        words = word_count(p)
        added = max(0, words - int(baseline.get("words", 0)))
        return Reading(_clamp(added / target), f"{added} of {target:.0f} new words ({words} total)")


# ------------------------------------------------------------------- folder
class FolderSource:
    """config: path, pattern (glob, recursive), count."""

    def baseline(self, config: dict[str, Any]) -> dict[str, Any]:
        p = Path(config.get("path", ""))
        if not p.is_dir():
            raise SourceError(f"Folder not found: {p}")
        return {"since": time.time()}

    def read(self, config: dict[str, Any], baseline: dict[str, Any]) -> Reading:
        p = Path(config.get("path", ""))
        if not p.is_dir():
            raise SourceError(f"Folder not found: {p}")
        pattern = config.get("pattern", "*") or "*"
        target = max(1, int(config.get("count", 1) or 1))
        since = float(baseline.get("since", 0))
        found = []
        for f in p.rglob(pattern):
            try:
                if f.is_file() and f.stat().st_mtime >= since:
                    found.append(f.name)
            except OSError:
                continue
            if len(found) >= target * 4:
                break
        ev = f"{len(found)} of {target} new/updated '{pattern}' file(s)"
        if found:
            ev += f" (latest: {sorted(found)[-1]})"
        return Reading(_clamp(len(found) / target), ev)


SOURCES = {
    SourceType.GIT: GitSource(),
    SourceType.DOCUMENT: DocumentSource(),
    SourceType.FOLDER: FolderSource(),
}


def capture_baseline(m: Milestone) -> dict[str, Any]:
    src = SOURCES.get(m.source_type)
    return src.baseline(m.source_config) if src else {}


def read_progress(m: Milestone) -> Reading | None:
    src = SOURCES.get(m.source_type)
    if src is None:
        return None
    return src.read(m.source_config, m.baseline)
