"""The tablet fetches model audio by bare URL, with no token.

On 2026-10-01 every stored recording was silently skipped on Pepper: the
rater role had put the whole /authoring prefix behind the researcher fence
a week earlier, the audio route went with it, the player got 401 and gave
up. The route now lives on its own router, and this test fails if anyone
mounts that router behind a dependency again.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import authoring  # noqa: E402
from app.database import get_db  # noqa: E402
from app.services import stimulus_audio  # noqa: E402


class _Query:
    def __init__(self, item):
        self.item = item

    def filter(self, *_):
        return self

    def first(self):
        return self.item


class _Db:
    def __init__(self, item):
        self.item = item

    def query(self, *_):
        return _Query(self.item)


def _app(item):
    app = FastAPI()
    app.include_router(authoring.public_router, prefix="/authoring")
    app.dependency_overrides[get_db] = lambda: _Db(item)
    return TestClient(app)


def test_audio_is_served_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(stimulus_audio, "STIMULUS_DIR", tmp_path)
    item = SimpleNamespace(id=uuid.uuid4(), name="cap")
    sf.write(tmp_path / f"{item.id}.wav", np.zeros(1600, dtype="float32"), 16_000)
    r = _app(item).get(f"/authoring/items/{item.id}/audio")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert len(r.content) > 44


def test_missing_recording_is_a_404_not_a_401(tmp_path, monkeypatch):
    monkeypatch.setattr(stimulus_audio, "STIMULUS_DIR", tmp_path)
    item = SimpleNamespace(id=uuid.uuid4(), name="cap")
    assert _app(item).get(f"/authoring/items/{item.id}/audio").status_code == 404


def test_the_public_router_holds_only_the_audio_route():
    """Anything else added to it would be unauthenticated authoring."""
    paths = {(r.path, tuple(sorted(r.methods))) for r in authoring.public_router.routes}
    assert paths == {("/items/{item_id}/audio", ("GET",))}


def test_the_live_app_mounts_it_outside_the_fence():
    from app.main import app
    from app.utils.auth import require_researcher
    audio = [r for r in app.routes if getattr(r, "path", "") == "/authoring/items/{item_id}/audio"
             and "GET" in getattr(r, "methods", set())]
    assert len(audio) == 1
    assert all(d.call is not require_researcher for d in audio[0].dependant.dependencies)
