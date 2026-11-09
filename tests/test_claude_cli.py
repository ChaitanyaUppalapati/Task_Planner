import json

import pytest

from taskplanner.ai import claude_cli
from taskplanner.core.models import Milestone, SourceType, Task, WorkType


def test_parse_structured_output():
    out = json.dumps({"is_error": False, "result": "", "structured_output": {"milestones": []}})
    assert claude_cli.parse_cli_output(out) == {"milestones": []}


def test_parse_result_with_fences():
    out = json.dumps({"is_error": False, "result": "Here:\n```json\n{\"milestones\": [1]}\n```"})
    assert claude_cli.parse_cli_output(out) == {"milestones": [1]}


def test_parse_error():
    with pytest.raises(claude_cli.ClaudeCliError):
        claude_cli.parse_cli_output(json.dumps({"is_error": True, "result": "Not logged in"}))


def test_to_breakdown_maps_evidence_to_linked_sources():
    task = Task(title="Feature", work_type=WorkType.CODING, milestones=[
        Milestone("link", source_type=SourceType.GIT, source_config={"repo": "/r"})])
    data = {"work_type": "coding", "total_minutes": 90, "milestones": [
        {"title": "Write API", "minutes": 45, "evidence": "git_commits", "target": 2},
        {"title": "Draft doc", "minutes": 30, "evidence": "document_words", "target": 300},
        {"title": "Ship", "minutes": 15, "evidence": "git_message", "pattern": "release"},
    ], "match_keywords": ["Feature", "api"]}
    b = claude_cli.to_breakdown(data, task)
    assert b.milestones[0].source_type == SourceType.GIT
    assert b.milestones[0].source_config["target"] == 2
    assert b.milestones[1].source_type == SourceType.MANUAL  # no document linked
    assert b.milestones[2].source_config["pattern"] == "release"
    assert b.match_keywords == ["feature", "api"]


def test_run_breakdown_invokes_cli(monkeypatch):
    captured = {}

    class P:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"is_error": False, "structured_output": {
            "work_type": "writing", "total_minutes": 60,
            "milestones": [{"title": "Outline", "minutes": 20, "evidence": "manual"}]}})

    def fake_run(args, **kw):
        captured["args"] = args
        captured["input"] = kw["input"]
        return P()

    monkeypatch.setattr(claude_cli, "find_claude", lambda p="": "/usr/bin/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    b = claude_cli.run_breakdown(Task(title="Essay on AI"))
    assert b.work_type == WorkType.WRITING and len(b.milestones) == 1
    assert "-p" in captured["args"] and "--json-schema" in captured["args"]
    assert captured["args"][captured["args"].index("--tools") + 1] == ""
    assert "Essay on AI" in captured["input"]


def test_missing_cli(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_claude", lambda p="": None)
    with pytest.raises(claude_cli.ClaudeCliError, match="not found"):
        claude_cli.run_breakdown(Task(title="x"))
