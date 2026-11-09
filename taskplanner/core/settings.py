"""User-configurable settings with defaults, persisted in the database."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from taskplanner.core.db import Database

DEFAULT_PRODUCTIVE_APPS = [
    "code.exe", "devenv.exe", "pycharm64.exe", "idea64.exe", "webstorm64.exe", "rider64.exe",
    "clion64.exe", "sublime_text.exe", "notepad++.exe", "windowsterminal.exe", "cmd.exe",
    "powershell.exe", "pwsh.exe", "wt.exe", "winword.exe", "excel.exe", "powerpnt.exe",
    "onenote.exe", "obsidian.exe", "notion.exe", "acrobat.exe", "acrord32.exe", "figma.exe",
    "matlab.exe", "rstudio.exe", "jupyter-lab.exe", "texstudio.exe", "zotero.exe",
    "cursor.exe", "claude.exe", "dbeaver.exe", "postman.exe", "blender.exe", "photoshop.exe",
]

DEFAULT_DISTRACTING_KEYWORDS = [
    "youtube", "netflix", "reddit", "twitter", " / x", "instagram", "facebook", "tiktok",
    "twitch", "prime video", "disney+", "hulu", "9gag", "steam", "epic games", "discord",
    "spotify", "whatsapp",
]

DEFAULT_DISTRACTING_APPS = ["steam.exe", "epicgameslauncher.exe", "spotify.exe", "discord.exe"]

DEFAULT_BROWSERS = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe"]


@dataclass
class Settings:
    daily_goal_minutes: int = 300          # earned (output) minutes per day
    work_start: str = "09:00"
    work_end: str = "17:00"
    break_minutes: int = 60
    idle_threshold_seconds: int = 180
    sample_interval_seconds: int = 5
    progress_check_seconds: int = 60
    drift_nudge_minutes: int = 3
    activity_retention_days: int = 180
    productive_apps: list[str] = field(default_factory=lambda: list(DEFAULT_PRODUCTIVE_APPS))
    distracting_apps: list[str] = field(default_factory=lambda: list(DEFAULT_DISTRACTING_APPS))
    distracting_keywords: list[str] = field(
        default_factory=lambda: list(DEFAULT_DISTRACTING_KEYWORDS)
    )
    browsers: list[str] = field(default_factory=lambda: list(DEFAULT_BROWSERS))
    excluded_apps: list[str] = field(default_factory=list)
    tracking_enabled: bool = True
    notifications_enabled: bool = True
    start_with_windows: bool = False
    ai_enabled: bool = True
    claude_path: str = ""                  # empty = find `claude` on PATH
    claude_model: str = ""                 # empty = CLI default
    ai_timeout_seconds: int = 240
    theme: str = "dark"
    onboarded: bool = False

    @property
    def available_minutes(self) -> float:
        start = _parse_hhmm(self.work_start)
        end = _parse_hhmm(self.work_end)
        if end <= start:
            end += 24 * 60
        return max(0.0, end - start - self.break_minutes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_hhmm(value: str) -> int:
    try:
        h, m = value.strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 9 * 60


def load_settings(db: Database) -> Settings:
    stored = db.get_setting("app_settings", {}) or {}
    s = Settings()
    valid = {f.name for f in fields(Settings)}
    for k, v in stored.items():
        if k in valid:
            setattr(s, k, v)
    return s


def save_settings(db: Database, settings: Settings) -> None:
    db.set_setting("app_settings", settings.to_dict())
