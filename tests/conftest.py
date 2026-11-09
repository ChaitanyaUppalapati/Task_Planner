import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from taskplanner.core.db import Database  # noqa: E402
from taskplanner.core.engine import Engine  # noqa: E402
from taskplanner.core.settings import Settings  # noqa: E402


class FakeClock:
    def __init__(self, t: float = 1_760_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def engine(db, settings, clock):
    return Engine(db, settings, clock=clock)
