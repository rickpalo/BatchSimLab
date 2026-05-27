"""Tests for append/replace export mode helpers."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from SmokeSimLab import (
    _find_next_job_index,
    _existing_jobs_for_bat,
    _job_run_cmd,
    _job_bat_block,
)


class TestFindNextJobIndex:
    def test_missing_dir_returns_zero(self, tmp_path):
        assert _find_next_job_index(str(tmp_path / "nonexistent")) == 0

    def test_empty_dir_returns_zero(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        assert _find_next_job_index(str(d)) == 0

    def test_single_job_returns_one(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        (d / "job_0000.json").write_text("{}")
        assert _find_next_job_index(str(d)) == 1

    def test_sequential_jobs(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        for i in range(5):
            (d / f"job_{i:04d}.json").write_text("{}")
        # 5 jobs (0-4) → next is 5
        assert _find_next_job_index(str(d)) == 5

    def test_non_sequential_uses_max(self, tmp_path):
        # If jobs 0, 2, 7 exist (gap), next is 8.
        d = tmp_path / "jobs"
        d.mkdir()
        for i in (0, 2, 7):
            (d / f"job_{i:04d}.json").write_text("{}")
        assert _find_next_job_index(str(d)) == 8

    def test_ignores_non_json_files(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        (d / "job_0000.json").write_text("{}")
        (d / "job_0001.log").write_text("log")
        (d / "job_0002.done").write_text("done")
        # Only .json files count
        assert _find_next_job_index(str(d)) == 1

    def test_ignores_non_job_json_files(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        (d / "job_0000.json").write_text("{}")
        (d / "config.json").write_text("{}")      # no "job_NNNN" pattern
        (d / "job_abc.json").write_text("{}")     # non-numeric suffix
        assert _find_next_job_index(str(d)) == 1

    def test_retry_log_ignored(self, tmp_path):
        # job_0000_retry.log must not be mistaken for a job JSON.
        d = tmp_path / "jobs"
        d.mkdir()
        (d / "job_0000.json").write_text("{}")
        (d / "job_0000_retry.log").write_text("log")
        assert _find_next_job_index(str(d)) == 1

    def test_large_index(self, tmp_path):
        d = tmp_path / "jobs"
        d.mkdir()
        (d / "job_9999.json").write_text("{}")
        assert _find_next_job_index(str(d)) == 10000

    # ── Semantic tests: append numbering starts correctly ────────────────────

    def test_append_after_five_jobs_starts_at_five(self, tmp_path):
        """Simulates: first batch had 5 jobs; append should start at index 5."""
        d = tmp_path / "jobs"
        d.mkdir()
        for i in range(5):
            (d / f"job_{i:04d}.json").write_text(json.dumps({"name": f"job_{i}"}))
        next_idx = _find_next_job_index(str(d))
        assert next_idx == 5
        # New jobs should be job_0005.json, job_0006.json, ...
        first_new = f"job_{next_idx:04d}.json"
        assert first_new == "job_0005.json"


# ── TODO-28: append must re-list previously exported jobs in the .bat ─────────

class TestExistingJobsForBat:
    """_existing_jobs_for_bat reads prior jobs so APPEND can re-list them.

    Regression for TODO-28: APPEND rewrote run_smoke_batch.bat in "w" mode with
    only the new jobs, silently dropping every earlier job from the launcher.
    """
    def _write_job(self, d, idx, name, render_mode="CYCLES"):
        (d / f"job_{idx:04d}.json").write_text(
            json.dumps({"name": name, "render_mode": render_mode})
        )

    def test_missing_dir_returns_empty(self, tmp_path):
        assert _existing_jobs_for_bat(str(tmp_path / "none"), 5) == []

    def test_returns_jobs_below_start_index(self, tmp_path):
        d = tmp_path / "jobs"; d.mkdir()
        self._write_job(d, 0, "R64", "CYCLES")
        self._write_job(d, 1, "R128", "EEVEE")
        result = _existing_jobs_for_bat(str(d), 2)
        assert result == [(0, "R64", "CYCLES"), (1, "R128", "EEVEE")]

    def test_excludes_jobs_at_or_above_start_index(self, tmp_path):
        # Newly written jobs (idx >= start) must not be double-listed.
        d = tmp_path / "jobs"; d.mkdir()
        self._write_job(d, 0, "R64")
        self._write_job(d, 1, "R128")   # this is the first NEW job
        self._write_job(d, 2, "R256")
        result = _existing_jobs_for_bat(str(d), 1)
        assert [idx for idx, _, _ in result] == [0]

    def test_sorted_by_index(self, tmp_path):
        d = tmp_path / "jobs"; d.mkdir()
        for idx in (3, 0, 2, 1):
            self._write_job(d, idx, f"job{idx}")
        result = _existing_jobs_for_bat(str(d), 10)
        assert [idx for idx, _, _ in result] == [0, 1, 2, 3]

    def test_missing_fields_use_defaults(self, tmp_path):
        d = tmp_path / "jobs"; d.mkdir()
        (d / "job_0000.json").write_text("{}")           # no name / render_mode
        result = _existing_jobs_for_bat(str(d), 1)
        assert result == [(0, "job_0000", "CYCLES")]

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        d = tmp_path / "jobs"; d.mkdir()
        (d / "job_0000.json").write_text("{not valid json")
        result = _existing_jobs_for_bat(str(d), 1)
        assert result == [(0, "job_0000", "CYCLES")]


class TestJobRunCmd:
    def test_uses_launcher_when_present(self):
        cmd = _job_run_cmd("py.exe", "L.py", "W.py", "b.exe", "f.blend",
                           "j.json", "CYCLES", launcher_exists=True)
        assert cmd == '"py.exe" "L.py" "b.exe" "j.json"'

    def test_eevee_fallback_windowed(self):
        cmd = _job_run_cmd("py.exe", "L.py", "W.py", "b.exe", "f.blend",
                           "j.json", "EEVEE", launcher_exists=False)
        assert "--window-geometry" in cmd
        assert "--background" not in cmd
        assert '"W.py"' in cmd

    def test_cycles_fallback_background(self):
        cmd = _job_run_cmd("py.exe", "L.py", "W.py", "b.exe", "f.blend",
                           "j.json", "CYCLES", launcher_exists=False)
        assert "--background" in cmd
        assert "2>nul" in cmd


class TestJobBatBlock:
    def test_block_structure(self):
        block = _job_bat_block(3, 10, "R128", '"run" "cmd"',
                               r"C:\out\jobs\job_0002.done")
        assert block[0] == "echo === Job 3/10: R128 ==="
        assert block[1] == '"run" "cmd"'
        # error branch increments ERRORS and writes an error .done sentinel
        assert any("set /a ERRORS+=1" in ln for ln in block)
        assert any('echo error exit' in ln and "job_0002.done" in ln for ln in block)
        # success branch writes a plain done sentinel
        assert any(ln.strip().startswith("echo done R128") for ln in block)
