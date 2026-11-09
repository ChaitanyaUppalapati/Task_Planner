import subprocess
import time
import zipfile

import pytest

from taskplanner.progress import sources


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "init")
    return r


def test_git_commits(repo):
    src = sources.GitSource()
    cfg = {"repo": str(repo), "metric": "commits", "target": 2}
    base = src.baseline(cfg)
    assert src.read(cfg, base).progress == 0
    (repo / "b.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "feat: login form")
    assert src.read(cfg, base).progress == 0.5


def test_git_lines_includes_uncommitted_and_untracked(repo):
    src = sources.GitSource()
    cfg = {"repo": str(repo), "metric": "lines", "target": 10}
    base = src.baseline(cfg)
    (repo / "a.txt").write_text("one\ntwo\nthree\n")
    (repo / "new.py").write_text("a\nb\nc\n")
    r = src.read(cfg, base)
    assert r.progress == pytest.approx(0.5)


def test_git_message(repo):
    src = sources.GitSource()
    cfg = {"repo": str(repo), "metric": "message", "pattern": "LOGIN"}
    base = src.baseline(cfg)
    assert src.read(cfg, base).progress == 0
    (repo / "b.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "feat: login form")
    assert src.read(cfg, base).progress == 1


def test_git_missing_repo(tmp_path):
    with pytest.raises(sources.SourceError):
        sources.GitSource().baseline({"repo": str(tmp_path / "nope")})


def test_git_empty_repo(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    git(r, "init", "-q")
    cfg = {"repo": str(r), "metric": "commits", "target": 1}
    base = sources.GitSource().baseline(cfg)
    assert base["head"] is None
    assert sources.GitSource().read(cfg, base).progress == 0


def make_docx(path, text):
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text +
           '</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_docx_word_count(tmp_path):
    p = tmp_path / "report.docx"
    make_docx(p, "one two three four")
    assert sources.word_count(p) == 4


def test_tex_word_count_strips_commands(tmp_path):
    p = tmp_path / "paper.tex"
    p.write_text("\\section{Intro} hello world % a comment\n\\textbf{bold}")
    assert sources.word_count(p) == 4  # Intro hello world bold


def test_document_progress(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("a b")
    src = sources.DocumentSource()
    cfg = {"path": str(p), "target_words": 4}
    base = src.baseline(cfg)
    p.write_text("a b c d")
    assert src.read(cfg, base).progress == 0.5


def test_folder_progress(tmp_path):
    (tmp_path / "old.pdf").write_text("x")
    src = sources.FolderSource()
    cfg = {"path": str(tmp_path), "pattern": "*.pdf", "count": 2}
    base = src.baseline(cfg)
    base["since"] = time.time() + 0.5
    time.sleep(0.6)
    (tmp_path / "hw3.pdf").write_text("x")
    assert src.read(cfg, base).progress == 0.5
