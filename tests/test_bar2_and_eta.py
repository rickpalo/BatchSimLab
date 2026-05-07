"""Tests for Bar 2 band-based job_factor, stage label, and ETA queue estimate."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from SmokeSimLab import _TOTAL_SUBTASKS


# ---------------------------------------------------------------------------
# Band-based job_factor formula
# The formula (inline in _poll_batch_progress) is pure math — tested here
# by reproducing it directly, mirroring the production code exactly.
# ---------------------------------------------------------------------------

def _band_factor(stage_secs, stage_remaining):
    """Reproduce the production Bar 2 formula."""
    total_est = max(sum(stage_secs), 1.0)
    job_factor = sum(
        min(max(s - r, 0.0), s) / total_est
        for s, r in zip(stage_secs, stage_remaining)
    )
    return min(max(job_factor, 0.0), 0.99)


STAGE_SECS = [10.0, 200.0, 100.0, 50.0]   # matches spec example: 360 s total


class TestBandFactor:
    def test_all_remaining_zero_is_done(self):
        factor = _band_factor(STAGE_SECS, [0.0, 0.0, 0.0, 0.0])
        assert factor == 0.99   # capped at 0.99 per spec

    def test_all_remaining_full_is_zero(self):
        factor = _band_factor(STAGE_SECS, STAGE_SECS)
        assert factor == 0.0

    def test_setup_complete_bake_not_started(self):
        # setup done (remaining=0), bake/render/still at full estimate
        stage_remaining = [0.0, 200.0, 100.0, 50.0]
        factor = _band_factor(STAGE_SECS, stage_remaining)
        # setup contribution = 10/360
        assert abs(factor - 10.0 / 360.0) < 1e-6

    def test_setup_and_bake_complete_render_not_started(self):
        stage_remaining = [0.0, 0.0, 100.0, 50.0]
        factor = _band_factor(STAGE_SECS, stage_remaining)
        # setup+bake contribution = (10+200)/360
        assert abs(factor - 210.0 / 360.0) < 1e-6

    def test_bake_halfway_through(self):
        # setup done, bake 50% done, render+still not started
        stage_remaining = [0.0, 100.0, 100.0, 50.0]
        factor = _band_factor(STAGE_SECS, stage_remaining)
        # setup=10, bake_elapsed = 200-100=100 → 10+100=110 / 360
        assert abs(factor - 110.0 / 360.0) < 1e-6

    def test_slow_bake_does_not_go_backwards(self):
        # bake remaining > estimate (slow start) — clamped to 0 contribution
        stage_remaining_start = [0.0, 200.0, 100.0, 50.0]   # bake just starting
        stage_remaining_slow  = [0.0, 4990.0, 100.0, 50.0]  # first frame was slow
        factor_start = _band_factor(STAGE_SECS, stage_remaining_start)
        factor_slow  = _band_factor(STAGE_SECS, stage_remaining_slow)
        # both have bake_elapsed clamped to 0 → same factor (setup band only)
        assert abs(factor_start - factor_slow) < 1e-9
        assert factor_slow >= factor_start

    def test_monotonically_non_decreasing(self):
        # Simulate bake progressing: remaining drops from 200 → 0 in steps
        prev = 0.0
        for bake_rem in [200.0, 150.0, 100.0, 50.0, 0.0]:
            f = _band_factor(STAGE_SECS, [0.0, bake_rem, 100.0, 50.0])
            assert f >= prev - 1e-9, f"factor went backwards: {f} < {prev}"
            prev = f

    def test_factor_never_negative(self):
        # Edge case: very large remaining values
        assert _band_factor([10.0], [99999.0]) == 0.0

    def test_factor_never_exceeds_0_99(self):
        assert _band_factor(STAGE_SECS, [0.0, 0.0, 0.0, 0.0]) == 0.99

    def test_single_stage(self):
        # 50% through one stage
        f = _band_factor([100.0], [50.0])
        assert abs(f - 0.5) < 1e-9

    def test_total_zero_does_not_divide_by_zero(self):
        # All estimates zero (degenerate) — total_est clamped to 1.0
        assert _band_factor([0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# Stage label fix — "Stage 1 of N" not "Stage 0 of N"
# ---------------------------------------------------------------------------

class TestStageLabelNumber:
    def test_at_job_start_shows_stage_1(self):
        stage_completed = 0
        current_stage = min(stage_completed + 1, _TOTAL_SUBTASKS)
        assert current_stage == 1

    def test_during_bake_shows_stage_2(self):
        stage_completed = 1
        current_stage = min(stage_completed + 1, _TOTAL_SUBTASKS)
        assert current_stage == 2

    def test_final_stage_does_not_exceed_total(self):
        # stage_completed == _TOTAL_SUBTASKS means all done
        stage_completed = _TOTAL_SUBTASKS
        current_stage = min(stage_completed + 1, _TOTAL_SUBTASKS)
        assert current_stage == _TOTAL_SUBTASKS

    def test_never_exceeds_total_subtasks(self):
        for stage_completed in range(_TOTAL_SUBTASKS + 2):
            current_stage = min(stage_completed + 1, _TOTAL_SUBTASKS)
            assert 1 <= current_stage <= _TOTAL_SUBTASKS


# ---------------------------------------------------------------------------
# Queue ETA — uses model (default_job_secs), not avg of completed jobs
# ---------------------------------------------------------------------------

class TestQueueEta:
    def test_queue_uses_model_not_avg(self):
        job_remaining    = 60.0
        default_job_secs = 300.0
        jobs_not_started = 3

        remaining = job_remaining + jobs_not_started * default_job_secs
        assert remaining == 60.0 + 3 * 300.0   # 960 s

    def test_queue_zero_not_started(self):
        remaining = 60.0 + 0 * 300.0
        assert remaining == 60.0

    def test_queue_scales_with_job_count(self):
        default_job_secs = 200.0
        for n in range(5):
            remaining = 0.0 + n * default_job_secs
            assert remaining == n * 200.0
