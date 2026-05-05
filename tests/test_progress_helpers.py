"""Tests for progress-bar helper functions: _format_eta and _count_png_frames."""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from SmokeSimLab import _count_png_frames, _format_eta


# ---------------------------------------------------------------------------
# _format_eta
# ---------------------------------------------------------------------------

class TestFormatEta:
    def test_zero_seconds(self):
        s = _format_eta(0)
        assert "0s" in s and "remaining" in s

    def test_under_one_minute(self):
        s = _format_eta(45)
        assert "45s" in s and "remaining" in s

    def test_exactly_one_minute(self):
        s = _format_eta(60)
        assert "1 min" in s and "remaining" in s

    def test_minutes(self):
        s = _format_eta(150)
        assert "2 min" in s and "remaining" in s

    def test_one_hour(self):
        s = _format_eta(3600)
        assert "1h" in s

    def test_hours_and_minutes(self):
        s = _format_eta(3660)
        assert "1h" in s and "1min" in s

    def test_under_sixty_is_seconds_not_minutes(self):
        assert "min" not in _format_eta(59)


# ---------------------------------------------------------------------------
# _count_png_frames
# ---------------------------------------------------------------------------

def _make_job(tmp_path, frame_end=5, name="MyJob"):
    """Write a minimal job JSON and return (jobs_dir, frames_dir)."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    frames_dir = tmp_path / "Renders" / f"{name}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    job_data = {"frame_end": frame_end, "output_path": str(tmp_path), "name": name}
    (jobs_dir / "job_0000.json").write_text(json.dumps(job_data))
    return jobs_dir, frames_dir


class TestCountPngFrames:
    def test_returns_none_on_missing_json(self, tmp_path):
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        assert _count_png_frames(str(jobs_dir), "job_0000") is None

    def test_empty_frames_dir_returns_zero(self, tmp_path):
        jobs_dir, _ = _make_job(tmp_path)
        count, total = _count_png_frames(str(jobs_dir), "job_0000")
        assert count == 0
        assert total == 5

    def test_counts_all_frames_without_since(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=5)
        for i in range(1, 6):
            (frames_dir / f"frame_{i:04d}.png").write_bytes(b"")
        count, total = _count_png_frames(str(jobs_dir), "job_0000")
        assert count == 5
        assert total == 5

    def test_since_zero_behaves_like_no_since(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=3)
        for i in range(1, 4):
            (frames_dir / f"frame_{i:04d}.png").write_bytes(b"")
        count, total = _count_png_frames(str(jobs_dir), "job_0000", since=0.0)
        assert count == 3
        assert total == 3

    def test_since_filters_old_frames(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=5)
        t_old = time.time() - 200
        t_new = time.time()
        cutoff = time.time() - 100   # 100 s ago

        for i in range(1, 6):
            f = frames_dir / f"frame_{i:04d}.png"
            f.write_bytes(b"")
            mtime = t_old if i <= 3 else t_new   # frames 1-3 old, 4-5 new
            os.utime(str(f), (mtime, mtime))

        count, total = _count_png_frames(str(jobs_dir), "job_0000", since=cutoff)
        assert count == 2   # only frames 4 and 5
        assert total == 5

    def test_since_future_returns_zero(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=3)
        for i in range(1, 4):
            (frames_dir / f"frame_{i:04d}.png").write_bytes(b"")
        future = time.time() + 9999
        count, total = _count_png_frames(str(jobs_dir), "job_0000", since=future)
        assert count == 0
        assert total == 3

    def test_ignores_non_png_files(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=3)
        (frames_dir / "frame_0001.png").write_bytes(b"")
        (frames_dir / "frame_0002.jpg").write_bytes(b"")   # wrong extension
        (frames_dir / "result.png").write_bytes(b"")       # wrong name pattern
        count, _ = _count_png_frames(str(jobs_dir), "job_0000")
        assert count == 1

    def test_frame_end_comes_from_json(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=250)
        (frames_dir / "frame_0001.png").write_bytes(b"")
        _, total = _count_png_frames(str(jobs_dir), "job_0000")
        assert total == 250

    def test_missing_frames_dir_returns_zero_count(self, tmp_path):
        jobs_dir, frames_dir = _make_job(tmp_path, frame_end=5)
        # Don't create the frames directory
        frames_dir.rmdir()
        count, total = _count_png_frames(str(jobs_dir), "job_0000")
        assert count == 0
        assert total == 5
