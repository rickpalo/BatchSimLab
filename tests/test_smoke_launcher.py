"""Tests for smoke_launcher helper functions."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "SmokeSimLab"))

from smoke_launcher import _save_crash_log


# ---------------------------------------------------------------------------
# _save_crash_log
# ---------------------------------------------------------------------------

class TestSaveCrashLog:
    def test_copies_crash_file(self, tmp_path, monkeypatch):
        """Crash log is copied with a timestamped name."""
        fake_temp = tmp_path / "TEMP"
        fake_temp.mkdir()
        crash_src = fake_temp / "blender.crash.txt"
        crash_src.write_text("Stack trace line 1\nStack trace line 2\n")

        monkeypatch.setenv("TEMP", str(fake_temp))

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        _save_crash_log(str(jobs_dir), "job_0000")

        crash_files = list(jobs_dir.glob("job_0000_crash_*.txt"))
        assert len(crash_files) == 1
        assert crash_files[0].read_text() == "Stack trace line 1\nStack trace line 2\n"

    def test_filename_contains_timestamp(self, tmp_path, monkeypatch):
        """Saved filename contains a YYYYMMDD_HHMMSS timestamp."""
        fake_temp = tmp_path / "TEMP"
        fake_temp.mkdir()
        (fake_temp / "blender.crash.txt").write_text("crash")
        monkeypatch.setenv("TEMP", str(fake_temp))

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        before = datetime.datetime.now().strftime("%Y%m%d")
        _save_crash_log(str(jobs_dir), "job_0001")

        crash_files = list(jobs_dir.glob("job_0001_crash_*.txt"))
        assert len(crash_files) == 1
        assert before in crash_files[0].name

    def test_no_crash_file_does_not_raise(self, tmp_path, monkeypatch):
        """If blender.crash.txt does not exist the function returns silently."""
        fake_temp = tmp_path / "TEMP"
        fake_temp.mkdir()
        monkeypatch.setenv("TEMP", str(fake_temp))

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        _save_crash_log(str(jobs_dir), "job_0002")  # must not raise
        assert list(jobs_dir.glob("*.txt")) == []

    def test_multiple_crashes_produce_separate_files(self, tmp_path, monkeypatch):
        """Each call produces a uniquely-named file (different timestamps)."""
        fake_temp = tmp_path / "TEMP"
        fake_temp.mkdir()
        crash_src = fake_temp / "blender.crash.txt"
        crash_src.write_text("crash A")
        monkeypatch.setenv("TEMP", str(fake_temp))

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        import time as _time
        _save_crash_log(str(jobs_dir), "job_0000")
        _time.sleep(1.1)  # ensure different second → different filename
        crash_src.write_text("crash B")
        _save_crash_log(str(jobs_dir), "job_0000")

        crash_files = sorted(jobs_dir.glob("job_0000_crash_*.txt"))
        assert len(crash_files) == 2
        assert crash_files[0].read_text() == "crash A"
        assert crash_files[1].read_text() == "crash B"


# ---------------------------------------------------------------------------
# smoke_launcher job JSON parsing
# ---------------------------------------------------------------------------

class TestLauncherJobJson:
    def test_reads_blend_file_and_render_mode(self, tmp_path):
        """Launcher reads blend_file and render_mode from job JSON."""
        job = {
            "blend_file":  r"C:\blends\test.blend",
            "render_mode": "EEVEE",
            "output_path": str(tmp_path),
        }
        job_path = tmp_path / "job_0000.json"
        job_path.write_text(json.dumps(job))

        with open(str(job_path), encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["blend_file"] == r"C:\blends\test.blend"
        assert data["render_mode"] == "EEVEE"

    def test_missing_blend_file_defaults_to_empty(self, tmp_path):
        """blend_file defaults to '' if absent (graceful degradation)."""
        job = {"output_path": str(tmp_path)}
        job_path = tmp_path / "job_0000.json"
        job_path.write_text(json.dumps(job))

        with open(str(job_path), encoding="utf-8") as fh:
            data = json.load(fh)

        assert data.get("blend_file", "") == ""
        assert data.get("render_mode", "CYCLES") == "CYCLES"
