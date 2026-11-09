"""AI task breakdown through the locally installed Claude Code CLI.

Runs ``claude -p`` in headless mode so the breakdown is billed to the user's
Claude subscription (whatever account the CLI is logged in with). No API key
is stored by this app. All tools are disabled for the call and it runs in an
empty temporary directory, so Claude cannot read or modify any files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from taskplanner.core.models import Milestone, SourceType, Task, WorkType

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

EVIDENCE_KINDS = ["git_commits", "git_lines", "git_message", "document_words", "folder_files",
                  "manual"]

SCHEMA = {
    "type": "object",
    "properties": {
        "work_type": {"type": "string", "enum": [w.value for w in WorkType]},
        "total_minutes": {"type": "number"},
        "milestones": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "minutes": {"type": "number"},
                    "evidence": {"type": "string", "enum": EVIDENCE_KINDS},
                    "target": {"type": "number"},
                    "pattern": {"type": "string"},
                    "done_when": {"type": "string"},
                },
                "required": ["title", "minutes", "evidence"],
            },
        },
        "match_keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "notes": {"type": "string"},
    },
    "required": ["work_type", "total_minutes", "milestones"],
}

PROMPT = """You are the planning engine of a productivity app that rewards finishing \
work in as little focused time as possible. Break the task below into 2-8 concrete, \
verifiable milestones, each with a realistic estimate of *focused* minutes for this \
person (no padding, no breaks). Be honest and specific - estimates become the "par" \
the user tries to beat.

For each milestone choose the best automatic evidence of real progress:
- git_commits: progress = new commits in the linked repo (set target = number of commits)
- git_lines: progress = lines changed in the linked repo (set target = lines)
- git_message: done when a commit message contains `pattern`
- document_words: progress = new words in the linked document (set target = words)
- folder_files: done when `target` new files appear in the linked folder (`pattern` = glob)
- manual: user ticks it off (use only when nothing on disk proves progress)
Only use git_* if a repository is linked, document_words if a document is linked, \
folder_files if a folder is linked.

Also return up to 6 short lowercase keywords likely to appear in window titles while \
working on it (file names, project names, site names).

Task title: {title}
Work type (user's guess): {work_type}
Description: {description}
User's own time guess: {guess}
Linked repository: {repo}
Linked document: {document}
Linked folder: {folder}
"""

JSON_ONLY_SUFFIX = (
    "\n\nReply with ONLY a JSON object (no prose, no code fences) matching this JSON "
    "Schema:\n{schema}"
)


class ClaudeCliError(Exception):
    pass


@dataclass
class Breakdown:
    work_type: WorkType
    total_minutes: float
    milestones: list[Milestone]
    match_keywords: list[str] = field(default_factory=list)
    notes: str = ""


def find_claude(configured: str = "") -> str | None:
    if configured:
        return configured if Path(configured).exists() or shutil.which(configured) else None
    found = shutil.which("claude")
    if found:
        return found
    candidates = []
    if sys.platform == "win32":
        home = Path.home()
        candidates += [
            home / ".local" / "bin" / "claude.exe",
            Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
        ]
    else:
        candidates += [Path.home() / ".local" / "bin" / "claude", Path("/usr/local/bin/claude")]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def _command_prefix(exe: str) -> tuple[list[str], bool]:
    """Return the argv prefix and whether rich arguments (JSON) are safe to pass.

    npm installs ``claude.cmd``; cmd.exe mangles quotes/braces in arguments, so
    run the bundled cli.js with node directly when we can find it.
    """
    if exe.lower().endswith((".cmd", ".bat")):
        base = Path(exe).parent
        cli = base / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        node = base / "node.exe"
        node_cmd = str(node) if node.is_file() else shutil.which("node")
        if cli.is_file() and node_cmd:
            return [node_cmd, str(cli)], True
        return [exe], False
    return [exe], True


def build_prompt(task: Task) -> str:
    repo = document = folder = "none"
    for m in task.milestones:
        cfg = m.source_config or {}
        if m.source_type == SourceType.GIT and cfg.get("repo"):
            repo = cfg["repo"]
        elif m.source_type == SourceType.DOCUMENT and cfg.get("path"):
            document = cfg["path"]
        elif m.source_type == SourceType.FOLDER and cfg.get("path"):
            folder = cfg["path"]
    return PROMPT.format(
        title=task.title.strip(),
        work_type=task.work_type.value,
        description=(task.description or "").strip() or "(none)",
        guess=f"{task.user_guess_minutes:.0f} minutes" if task.user_guess_minutes else "none",
        repo=repo,
        document=document,
        folder=folder,
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ClaudeCliError("Claude did not return JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ClaudeCliError(f"Could not parse Claude's JSON: {e}") from e


def parse_cli_output(stdout: str) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return _extract_json(stdout)
    if not isinstance(envelope, dict):
        raise ClaudeCliError("Unexpected output from claude CLI")
    if envelope.get("is_error"):
        raise ClaudeCliError(str(envelope.get("result") or envelope.get("subtype") or "error"))
    if isinstance(envelope.get("structured_output"), dict):
        return envelope["structured_output"]
    if "milestones" in envelope:
        return envelope
    result = envelope.get("result")
    if isinstance(result, str):
        return _extract_json(result)
    raise ClaudeCliError("Claude returned no result")


def to_breakdown(data: dict, task: Task) -> Breakdown:
    links = {m.source_type: m.source_config for m in task.milestones if m.source_config}
    git_cfg = links.get(SourceType.GIT, {})
    doc_cfg = links.get(SourceType.DOCUMENT, {})
    folder_cfg = links.get(SourceType.FOLDER, {})

    milestones = []
    for item in data.get("milestones", [])[:12]:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        minutes = max(1.0, float(item.get("minutes") or 0) or 15.0)
        kind = item.get("evidence", "manual")
        target = item.get("target")
        pattern = str(item.get("pattern") or "").strip()
        st, cfg = SourceType.MANUAL, {}
        if kind.startswith("git_") and git_cfg.get("repo"):
            st = SourceType.GIT
            metric = {"git_commits": "commits", "git_lines": "lines",
                      "git_message": "message"}.get(kind, "commits")
            cfg = {"repo": git_cfg["repo"], "metric": metric,
                   "target": float(target or (1 if metric != "lines" else 100))}
            if metric == "message":
                cfg["pattern"] = pattern or title.split()[0]
        elif kind == "document_words" and doc_cfg.get("path"):
            st = SourceType.DOCUMENT
            cfg = {"path": doc_cfg["path"], "target_words": float(target or 500)}
        elif kind == "folder_files" and folder_cfg.get("path"):
            st = SourceType.FOLDER
            cfg = {"path": folder_cfg["path"], "pattern": pattern or folder_cfg.get("pattern", "*"),
                   "count": int(target or 1)}
        done_when = str(item.get("done_when") or "").strip()
        milestones.append(Milestone(title=title, guess_minutes=minutes, source_type=st,
                                    source_config=cfg, evidence=done_when))
    if not milestones:
        raise ClaudeCliError("Claude returned no milestones")
    try:
        work_type = WorkType(data.get("work_type", task.work_type.value))
    except ValueError:
        work_type = task.work_type
    total = float(data.get("total_minutes") or 0) or sum(m.guess_minutes or 0 for m in milestones)
    keywords = [str(k).strip().lower() for k in data.get("match_keywords", []) if str(k).strip()]
    return Breakdown(work_type, total, milestones, keywords[:6], str(data.get("notes", "")))


def run_breakdown(task: Task, claude_path: str = "", model: str = "",
                  timeout: float = 240) -> Breakdown:
    exe = find_claude(claude_path)
    if not exe:
        raise ClaudeCliError(
            "Claude Code CLI not found. Install it (https://claude.com/claude-code), run "
            "`claude` once to log in with your subscription, or set its path in Settings."
        )
    prefix, rich_args = _command_prefix(exe)
    prompt = build_prompt(task)
    args = [*prefix, "-p", "--output-format", "json", "--no-session-persistence"]
    if rich_args:
        args += ["--json-schema", json.dumps(SCHEMA), "--tools", ""]
    else:
        prompt += JSON_ONLY_SUFFIX.format(schema=json.dumps(SCHEMA))
    if model:
        args += ["--model", model]

    with tempfile.TemporaryDirectory(prefix="taskplanner-ai-") as cwd:
        try:
            proc = subprocess.run(
                args, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:
            raise ClaudeCliError(f"Claude took longer than {timeout:.0f}s") from e
        except OSError as e:
            raise ClaudeCliError(f"Could not start Claude CLI: {e}") from e
    if proc.returncode != 0 and not proc.stdout.strip():
        msg = (proc.stderr or "").strip().splitlines()
        hint = msg[-1] if msg else f"exit code {proc.returncode}"
        if "login" in hint.lower() or "auth" in hint.lower():
            hint += " - run `claude` in a terminal once to sign in."
        raise ClaudeCliError(f"Claude CLI failed: {hint}")
    return to_breakdown(parse_cli_output(proc.stdout), task)
