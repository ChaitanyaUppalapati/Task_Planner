"""Platform sampler selection."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Protocol

from taskplanner.core.models import ActivitySample


class Sampler(Protocol):
    def sample(self) -> ActivitySample: ...


class X11Sampler:
    """Best-effort development sampler for Linux desktops with xdotool."""

    def sample(self) -> ActivitySample:
        title, process = "", ""
        try:
            wid = subprocess.run(["xdotool", "getactivewindow"], capture_output=True,
                                 text=True, timeout=2).stdout.strip()
            if wid:
                title = subprocess.run(["xdotool", "getwindowname", wid], capture_output=True,
                                       text=True, timeout=2).stdout.strip()
                pid = subprocess.run(["xdotool", "getwindowpid", wid], capture_output=True,
                                     text=True, timeout=2).stdout.strip()
                if pid:
                    with open(f"/proc/{pid}/comm") as fh:
                        process = fh.read().strip().lower()
        except (OSError, subprocess.SubprocessError):
            pass
        return ActivitySample(time.time(), process, title, 0.0)


class NullSampler:
    """Used where no window information is available (e.g. headless CI)."""

    def sample(self) -> ActivitySample:
        return ActivitySample(time.time(), "", "", 0.0)


class ScriptedSampler:
    """Replays a fixed list of samples; for tests and demos."""

    def __init__(self, samples: list[ActivitySample]):
        self._samples = list(samples)

    def sample(self) -> ActivitySample:
        if not self._samples:
            return ActivitySample(time.time(), "", "", 0.0)
        return self._samples.pop(0)


def default_sampler() -> Sampler:
    if sys.platform == "win32":
        from taskplanner.tracking.win32 import Win32Sampler

        return Win32Sampler()
    if shutil.which("xdotool"):
        return X11Sampler()
    return NullSampler()
