"""
Tests for smoke_worker.py:_read_stored_bake_time / _write_stored_bake_time.

The worker is a top-level script (not importable directly — its main body
calls sys.exit when no `--` argv is provided), but the bake-time helpers
are pure file-I/O and have no bpy dependency. We extract their source from
the worker file and exec it in an isolated namespace, which keeps tests
exercising the actual production code rather than a copy.
"""
import datetime
import json
import os
import pathlib
import tempfile

import pytest


_WORKER_SRC = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "BatchSimLab" / "smoke_worker.py"


def _load_helpers():
    """Extract the bake-time helper block from the worker source and exec it."""
    src = _WORKER_SRC.read_text(encoding="utf-8")
    start_marker = "# Cache bake-time sidecar"
    start = src.index(start_marker)
    while start > 0 and src[start - 1] != "\n":
        start -= 1
    end = src.index("# ---", start + 80)
    block = src[start:end]
    ns: dict = {
        "os": os, "json": json, "datetime": datetime,
        # _log is referenced in the OSError branch; stub it for standalone exec.
        "_log": lambda _msg: None,
    }
    exec(block, ns)
    return ns


# Module-level (NOT class attributes) so the helpers stay plain callables —
# binding them on the class would turn them into unbound methods that
# receive `self` as their first arg.
_NS       = _load_helpers()
_read     = _NS["_read_stored_bake_time"]
_write    = _NS["_write_stored_bake_time"]
_FILENAME = _NS["_BAKE_TIME_FILENAME"]


class TestBakeTimeSidecar:
    def test_filename_is_bake_time_json(self):
        # Stable file name — the worker uses it across versions.
        assert _FILENAME == "bake_time.json"

    def test_read_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            assert _read(d) is None

    def test_read_malformed_json_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, _FILENAME), "w", encoding="utf-8") as fh:
                fh.write("{not valid json")
            assert _read(d) is None

    def test_read_missing_key_returns_none(self):
        # KeyError-tolerant: a sidecar without the expected key is treated
        # the same as a missing file (no stale value gets surfaced).
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, _FILENAME), "w", encoding="utf-8") as fh:
                json.dump({"frames": 500}, fh)
            assert _read(d) is None

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, 191.4, 500, 128)
            assert _read(d) == pytest.approx(191.4)

    def test_write_rounds_to_two_decimals(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, 191.456789, 500, 128)
            assert _read(d) == pytest.approx(191.46)

    def test_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, 100.0, 250, 128)
            _write(d, 250.0, 500, 128)
            assert _read(d) == pytest.approx(250.0)

    def test_write_includes_all_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, 191.4, 500, 128)
            with open(os.path.join(d, _FILENAME), encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["bake_seconds"] == pytest.approx(191.4)
            assert data["frames"]     == 500
            assert data["resolution"] == 128
            # Timestamp must be parseable as ISO-8601
            datetime.datetime.fromisoformat(data["timestamp"])

    def test_write_int_coercion(self):
        # frames/resolution may arrive as floats from JSON. Must persist as ints.
        with tempfile.TemporaryDirectory() as d:
            _write(d, 100.0, 500.0, 128.0)
            with open(os.path.join(d, _FILENAME), encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data["frames"], int)
            assert isinstance(data["resolution"], int)

    def test_read_coerces_int_bake_seconds_to_float(self):
        # Hand-edited sidecar with an integer bake_seconds must still come
        # back as a float (downstream arithmetic depends on it).
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, _FILENAME), "w", encoding="utf-8") as fh:
                json.dump({"bake_seconds": 191}, fh)
            value = _read(d)
            assert isinstance(value, float)
            assert value == 191.0
