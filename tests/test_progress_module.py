"""TODO-58 module #4 regression tests: pure progress/ETA helpers live in progress.py.

The fourth extraction moved the *pure* half of the batch-progress machinery —
the jobs-dir scanners, the phase-aware ETA estimator, and the formatters (plus
their constants) — into ``BatchSimLab.progress`` and re-imported every name back
into the package ``__init__``.

The *stateful* half (the live poll engine + the rebindable ``_bt``/``_estim``/
``_job_*``/``_last_auto_index``/``_auto_retry_count`` globals + their mutators)
deliberately STAYED in ``__init__``: those globals are rebound from operators and
load handlers that also stay in ``__init__``, so splitting the variable across two
modules would diverge the binding.  This test pins that boundary: ``progress`` is
bpy-free and holds no addon mutable state, the names are reachable from the
package root as the *same* object, and the moved helpers still behave.
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

_PROGRESS_NAMES = [
    "_SETUP_SECS_DEFAULT",
    "_STILL_SECS_DEFAULT",
    "_DONE_RE",
    "_RETRY_DONE_RE",
    "_CRASHED_RE",
    "_LOG_DONE_MARKERS",
    "_find_running_log",
    "_count_vdb_frames",
    "_bake_progress_display",
    "_count_png_frames",
    "_format_eta",
    "_estimate_batch_remaining",
    "_format_elapsed",
    "_has_error",
    "_compute_batch_summary",
    "_pid_is_alive",
    "_live_job_pid",
]


@pytest.fixture(scope="module")
def pkg():
    return importlib.import_module("BatchSimLab")


@pytest.fixture(scope="module")
def progress():
    return importlib.import_module("BatchSimLab.progress")


def test_progress_is_a_submodule(progress):
    assert progress.__name__ == "BatchSimLab.progress"


def test_progress_is_bpy_free(progress):
    """The pure half must not import bpy — it is the unit-testable layer."""
    src = open(progress.__file__, encoding="utf-8").read()
    assert "import bpy" not in src, "progress.py must stay bpy-free (pure scanners/estimator)"


def test_progress_holds_no_stateful_engine(progress):
    """The rebindable batch-progress globals + the poll engine deliberately stay
    in __init__; guard against them accidentally migrating here (which would split
    a rebound global across two modules)."""
    for leaked in ("_poll_batch_progress_impl", "_batch_times", "_job_statuses",
                   "_job_log_rows", "_last_auto_index", "_update_job_log_statuses"):
        assert not hasattr(progress, leaked), (
            f"{leaked} must stay in __init__ with the mutable state it rebinds"
        )


@pytest.mark.parametrize("name", _PROGRESS_NAMES)
def test_name_defined_in_progress(progress, name):
    assert hasattr(progress, name), f"{name} must be defined in BatchSimLab.progress"


@pytest.mark.parametrize("name", _PROGRESS_NAMES)
def test_name_reexported_from_package(pkg, name):
    assert hasattr(pkg, name), (
        f"{name} must remain importable from the BatchSimLab package "
        f"(re-export from progress in __init__)"
    )


@pytest.mark.parametrize("name", _PROGRESS_NAMES)
def test_reexport_is_same_object(pkg, progress, name):
    assert getattr(pkg, name) is getattr(progress, name), (
        f"BatchSimLab.{name} and BatchSimLab.progress.{name} diverged — a "
        f"duplicate definition likely survived the extraction"
    )


def test_format_helpers_behave(progress):
    """Sanity on the pure formatters."""
    assert progress._format_eta(30) == "~30s remaining"
    assert progress._format_eta(90) == "~1 min remaining"
    assert progress._format_elapsed(45) == "45 sec"
    assert progress._format_elapsed(27 * 60) == "27 min"


def test_estimate_batch_remaining_counts_down_through_phases(progress):
    """Bake phase (current job not yet baked) charges every pending render its full
    cost; once we cross into the render phase the estimate is strictly smaller —
    the regression TODO-46 fixed."""
    common = dict(
        total=4, bake_done_n=0, render_done_n=0, bake_only=False,
        setup_remaining=0.0, bake_remaining=10.0, render_remaining=10.0,
        still_remaining=0.0, default_bake_secs=20.0, default_render_secs=30.0,
    )
    bake_phase = progress._estimate_batch_remaining(current_job_baked=False, **common)
    render_phase = progress._estimate_batch_remaining(current_job_baked=True, **common)
    assert bake_phase > render_phase > 0.0


class TestBakeProgressDisplay:
    """User-reported UX bug: resuming a bake showed session-relative numbers
    ("Baking (1 of 400)" for a 500-frame job resuming at frame 100) instead of
    the job's real overall position ("Baking (101 of 500)") — looked like the
    job had restarted from scratch even though it hadn't."""

    def test_fresh_job_no_baseline(self, progress):
        displayed, to_bake, factor = progress._bake_progress_display(
            baked_new=1, total_frames=500, bake_baseline=0)
        assert (displayed, to_bake) == (1, 500)
        assert factor == pytest.approx(1 / 500)

    def test_resumed_job_shows_absolute_position(self, progress):
        # 500-frame job, 100 already baked before this session started, 1 new
        # frame baked so far this session.
        displayed, to_bake, factor = progress._bake_progress_display(
            baked_new=1, total_frames=500, bake_baseline=100)
        assert displayed == 101                # NOT 1
        assert to_bake == 400                   # frames remaining this session
        assert factor == pytest.approx(1 / 400)  # bar still animates 0→1 per session

    def test_resume_completes_at_total(self, progress):
        displayed, _, factor = progress._bake_progress_display(
            baked_new=400, total_frames=500, bake_baseline=100)
        assert displayed == 500
        assert factor == 1.0

    def test_full_rebake_detected_drops_stale_baseline(self, progress):
        # Mantaflow ignored the resume hint and rebaked from frame 1 — every
        # frame gets a fresh mtime, so baked_new (450) alone already exceeds
        # what should have been "remaining" (400) under the old baseline.
        displayed, to_bake, factor = progress._bake_progress_display(
            baked_new=450, total_frames=500, bake_baseline=100)
        assert (displayed, to_bake) == (450, 500)
        assert factor == pytest.approx(450 / 500)


def test_find_running_log_on_tmpdir(progress, tmp_path):
    """End-to-end on a temp jobs dir: an active log with no .done marker is found;
    once its .done lands it is no longer the running job."""
    (tmp_path / "job_0000.log").write_text("Baking frame 3\n", encoding="utf-8")
    result = progress._find_running_log(str(tmp_path))
    assert result is not None and result[1] == "job_0000"

    (tmp_path / "job_0000.done").write_text("ok", encoding="utf-8")
    assert progress._find_running_log(str(tmp_path)) is None


def _exited_pid():
    """Spawn and wait on a trivial subprocess; return its now-dead PID."""
    import subprocess as sp
    proc = sp.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class TestLiveJobPid:
    """BUG-025: detect a batch still running in a *different* Blender session
    (e.g. the UI session restarted but the background launcher/Blender it
    spawned earlier did not) so Export Batch / Run Batch can refuse to
    clobber its job files instead of orphaning it."""

    def test_pid_is_alive_for_current_process(self, progress):
        assert progress._pid_is_alive(os.getpid()) is True

    def test_pid_is_not_alive_for_exited_process(self, progress):
        assert progress._pid_is_alive(_exited_pid()) is False

    def test_live_job_pid_none_without_pidfiles(self, progress, tmp_path):
        assert progress._live_job_pid(str(tmp_path)) is None

    def test_live_job_pid_none_for_missing_dir(self, progress, tmp_path):
        assert progress._live_job_pid(str(tmp_path / "does_not_exist")) is None

    def test_live_job_pid_found_for_running_pid(self, progress, tmp_path):
        (tmp_path / "job_0000.pid").write_text(str(os.getpid()), encoding="utf-8")
        assert progress._live_job_pid(str(tmp_path)) == ("job_0000", os.getpid())

    def test_live_job_pid_ignored_for_dead_pid(self, progress, tmp_path):
        (tmp_path / "job_0000.pid").write_text(str(_exited_pid()), encoding="utf-8")
        assert progress._live_job_pid(str(tmp_path)) is None

    def test_live_job_pid_matches_retry_stem(self, progress, tmp_path):
        (tmp_path / "job_0000_retry.pid").write_text(str(os.getpid()), encoding="utf-8")
        assert progress._live_job_pid(str(tmp_path)) == ("job_0000_retry", os.getpid())

    def test_live_job_pid_skips_malformed_file(self, progress, tmp_path):
        (tmp_path / "job_0000.pid").write_text("not-a-pid", encoding="utf-8")
        assert progress._live_job_pid(str(tmp_path)) is None
