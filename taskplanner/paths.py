"""Filesystem locations for user data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from taskplanner import APP_ID


def data_dir() -> Path:
    """Return (and create) the per-user data directory.

    Windows: %APPDATA%\\TaskPlanner. Elsewhere: $XDG_DATA_HOME/TaskPlanner.
    Can be overridden with the TASKPLANNER_DATA_DIR environment variable.
    """
    override = os.environ.get("TASKPLANNER_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "taskplanner.db"


def log_path() -> Path:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "taskplanner.log"
