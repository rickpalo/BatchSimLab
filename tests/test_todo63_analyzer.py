"""TODO-63 analyzer additions (tools/analyze_estim.py):
  * Part B  — _split_batches segments batch_eta_tick records per batch.
  * TODO-24 — _parse_frame_times / _blender_time_to_secs extract per-frame
              render timing from a captured console.log.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import analyze_estim as ae


class TestBlenderTimeParse:
    def test_mm_ss(self):
        assert ae._blender_time_to_secs("00:09.84") == pytest.approx(9.84)
        assert ae._blender_time_to_secs("02:30.00") == pytest.approx(150.0)

    def test_hh_mm_ss(self):
        assert ae._blender_time_to_secs("01:02:03.50") == pytest.approx(3723.50)

    def test_garbage_returns_none(self):
        assert ae._blender_time_to_secs("not-a-time") is None


class TestParseFrameTimes:
    SAMPLE = (
        "Fra:1 Mem:412.50M | Time:00:02.00 | Remaining:00:08.00 | Scene\n"
        "Fra:1 Mem:420.00M | Time:00:09.84 | Remaining:00:00.10 | Scene\n"   # later update, same frame
        "Saved: '/out/0001.png' Time: 00:09.90\n"
        "Fra:2 Mem:412.50M | Time:00:01.00 | Remaining:00:07.00 | Scene\n"
        "Fra:2 Mem:420.00M | Time:00:11.20 | Remaining:00:00.05 | Scene\n"
    )

    def test_keeps_max_time_per_frame(self):
        pf = ae._parse_frame_times(self.SAMPLE)
        assert pf[1] == pytest.approx(9.84)    # max for frame 1, not the 2.00 update
        assert pf[2] == pytest.approx(11.20)

    def test_ignores_non_matching_lines(self):
        pf = ae._parse_frame_times("Blender quit\nMantaflow baking...\n")
        assert pf == {}


class TestSplitBatches:
    def _recs(self):
        return [
            {"event": "batch_start", "jobs": 3},
            {"event": "batch_eta_tick", "elapsed": 0.0,   "remaining_secs": 3600.0, "phase": "bake"},
            {"event": "job_start", "job": "a"},                     # unrelated event ignored
            {"event": "batch_eta_tick", "elapsed": 600.0, "remaining_secs": 2400.0, "phase": "bake"},
            {"event": "batch_complete", "jobs": 3, "elapsed_secs": 3000.0},
            {"event": "batch_start", "jobs": 1},
            {"event": "batch_eta_tick", "elapsed": 0.0, "remaining_secs": 100.0, "phase": "render"},
        ]

    def test_two_batches_split_with_actual_total(self):
        batches = ae._split_batches(self._recs())
        assert len(batches) == 2
        assert len(batches[0]["ticks"]) == 2
        assert batches[0]["actual_total"] == 3000.0
        # Second batch has no batch_complete yet.
        assert batches[1]["actual_total"] is None
        assert len(batches[1]["ticks"]) == 1

    def test_no_ticks_means_no_batch(self):
        recs = [{"event": "batch_start"}, {"event": "batch_complete", "elapsed_secs": 5.0}]
        assert ae._split_batches(recs) == []

    def test_orphan_tick_after_complete_attaches_to_prior_batch(self):
        """A final tick that landed just AFTER batch_complete (older log order) must
        NOT spawn a phantom batch — it attaches to the most recent segment."""
        recs = [
            {"event": "batch_start"},
            {"event": "batch_eta_tick", "elapsed": 0.0, "remaining_secs": 100.0},
            {"event": "batch_complete", "elapsed_secs": 90.0},
            {"event": "batch_eta_tick", "elapsed": 90.0, "remaining_secs": 0.0},  # trailing
        ]
        batches = ae._split_batches(recs)
        assert len(batches) == 1
        assert len(batches[0]["ticks"]) == 2
        assert batches[0]["actual_total"] == 90.0
