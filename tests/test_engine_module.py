"""TODO-58 module #6b regression tests: the stateful run/poll engine lives in engine.py.

The 6b extraction moved the live batch-run / poll machinery — the poller, the
per-stage timing (_bt*) and estimate-logging (_estim*) helpers, the job-log status
updater, and the six run operators (run_batch / retry_failed / monitor_existing_jobs
/ remove_all_jobs / setup_results / reset_to_defaults) plus the two deferred timer
callbacks — into ``BatchSimLab.engine``.

This is the cluster module #4 deliberately kept OUT of the pure progress.py: it owns
the rebindable scalars (_last_auto_index / _auto_retry_count) and the in-place batch
state (_job_statuses / _job_log_rows / _batch_times / _estim / _poll_state).  Every
rebinder of the two scalars lives here, so ``global`` stays valid within one module.

This test pins the boundary: the names resolve from the package root as the SAME
object (mutable state + functions), the two rebindable scalars are engine-owned but
deliberately NOT re-exported (a re-imported int would be a stale snapshot), the UI /
PropertyGroups did NOT leak here, and the function-local deferred-import targets stay
reachable from the package.
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Re-exported from the package as the SAME object (functions + mutable state +
# true constants).  The two REBINDABLE scalars are intentionally excluded.
_ENGINE_REEXPORTED = [
    "_BAKE_DONE_RE", "_RENDER_DONE_RE", "_JOB_JSON_RE", "_jobs_needing_retry",
    "_batch_is_running",
    "_STAGES", "_TOTAL_SUBTASKS", "_update_job_log_statuses",
    "_batch_times", "_bt", "_bt_set", "_bt_reset_all",
    "_job_statuses", "_job_log_rows", "_MAX_AUTO_RETRIES", "_should_auto_retry",
    "_estim", "_debug_log", "_estim_log", "_estim_reset_job",
    "_POLLER_STALE_SECS", "_poll_state",
    "_poll_batch_progress", "_poll_batch_progress_impl", "_redraw_panels",
    "_auto_retry_deferred", "_setup_results_deferred",
    "SMOKE_OT_run_batch", "SMOKE_OT_retry_failed", "SMOKE_OT_setup_results",
    "SMOKE_OT_remove_all_jobs", "SMOKE_OT_monitor_existing_jobs",
    "SMOKE_OT_reset_to_defaults",
]

# Engine-owned but NOT re-exported from the package.
_ENGINE_PRIVATE = [
    "_last_auto_index", "_auto_retry_count",
    "_BAKE_RATE_PER_RES3_FRAME", "_RENDER_RATE_CYCLES_PER_PIXEL_FRAME",
    "_RENDER_RATE_EEVEE_PER_PIXEL_FRAME", "_BAKE_RATE_DEFAULT", "_RENDER_RATE_DEFAULT",
    "_BAKE_NOISE_UPRES_MULTIPLIER", "_BAKE_NOISE_UPRES_MULTIPLIER_DEFAULT",
    "_bake_noise_multiplier",
]

# Names engine's operators / _estim_log reach via a function-local deferred import
# (they live with the addon metadata / load handler in __init__).
_DEFERRED_TARGETS = [
    "ADDON_VERSION", "_read_helper_version",
    "_EXPECTED_WORKER_VERSION", "_EXPECTED_LAUNCHER_VERSION", "_reset_on_load",
]


@pytest.fixture(scope="module")
def pkg():
    return importlib.import_module("BatchSimLab")


@pytest.fixture(scope="module")
def engine():
    return importlib.import_module("BatchSimLab.engine")


def test_engine_is_a_submodule(engine):
    assert engine.__name__ == "BatchSimLab.engine"


def test_ui_did_not_leak_into_engine(engine):
    """The panel / UILists / PropertyGroups / Preferences belong to other modules;
    guard against any of them migrating into engine.py."""
    for ui in ("SMOKE_PT_panel", "SMOKE_UL_value_list", "SMOKE_UL_job_log",
               "SMOKE_UL_velocity_list", "SmokeSimLabPreferences",
               "ValueItem", "SmokeSettings", "_emitters_ui", "_noise_ui"):
        assert not hasattr(engine, ui), f"{ui} must not live in engine.py"


@pytest.mark.parametrize("name", _ENGINE_REEXPORTED)
def test_name_defined_in_engine(engine, name):
    assert hasattr(engine, name), f"{name} must be defined in BatchSimLab.engine"


@pytest.mark.parametrize("name", _ENGINE_REEXPORTED)
def test_name_reexported_from_package(pkg, name):
    assert hasattr(pkg, name), (
        f"{name} must remain importable from the BatchSimLab package "
        f"(re-export from engine in __init__)"
    )


@pytest.mark.parametrize("name", _ENGINE_REEXPORTED)
def test_reexport_is_same_object(pkg, engine, name):
    assert getattr(pkg, name) is getattr(engine, name), (
        f"BatchSimLab.{name} and BatchSimLab.engine.{name} diverged — a duplicate "
        f"definition likely survived the extraction"
    )


@pytest.mark.parametrize("name", _ENGINE_PRIVATE)
def test_private_name_defined_in_engine(engine, name):
    assert hasattr(engine, name), f"{name} must be defined in BatchSimLab.engine"


@pytest.mark.parametrize("name", ("_last_auto_index", "_auto_retry_count"))
def test_rebindable_scalars_not_reexported(pkg, name):
    """A re-imported int is a stale snapshot once engine rebinds it; the scalars are
    engine-internal and must NOT be re-exported from the package root."""
    assert not hasattr(pkg, name), (
        f"{name} is a rebindable scalar — must NOT be re-exported (stale snapshot)"
    )


@pytest.mark.parametrize("name", _DEFERRED_TARGETS)
def test_deferred_import_targets_reachable(pkg, name):
    """engine's run_batch / reset_to_defaults / _estim_log do `from . import <name>`
    at call time; if any stopped being reachable the operator would raise at runtime
    (not caught by import-time tests)."""
    assert hasattr(pkg, name), (
        f"{name} must stay reachable from the BatchSimLab package for engine's "
        f"deferred imports"
    )


def test_should_auto_retry_behaves(engine):
    assert engine._should_auto_retry(0, True, 0) is False   # no errors
    assert engine._should_auto_retry(2, False, 0) is False  # disabled
    assert engine._should_auto_retry(2, True, 0) is True
    assert engine._should_auto_retry(1, True, engine._MAX_AUTO_RETRIES) is False


def test_bake_noise_multiplier_behaves(engine):
    """TODO-51 (partial): noise sim adds a wavelet-turbulence up-res bake pass
    the flat per-res3 rate doesn't capture — calibrated from the 2026-06-22
    AutoTest sweep (analyze_estim.py BAKE table actual/default ratios)."""
    assert engine._bake_noise_multiplier(False, 2) == 1.0   # noise off: no change
    assert engine._bake_noise_multiplier(True, 0) == 1.0    # upres 0: baseline
    assert engine._bake_noise_multiplier(True, 1) == pytest.approx(2.3)
    assert engine._bake_noise_multiplier(True, 2) == pytest.approx(3.8)
    # upres 3+ unmeasured: falls back to the highest known bucket.
    assert engine._bake_noise_multiplier(True, 3) == engine._BAKE_NOISE_UPRES_MULTIPLIER_DEFAULT


class TestJobsNeedingRetry:
    """A job needs a retry when its final unphased marker says "error" OR when it
    has no final unphased .done at all (interrupted / never finished).  The
    phased .bake.done / .render.done are diagnostic and never count."""

    def _job(self, jobs, idx, *, done=None, retry_done=None, bake_done=None,
             render_done=None):
        """Write a job_NNNN.json (+ optional markers) into the jobs dir."""
        stem = f"job_{idx:04d}"
        (jobs / f"{stem}.json").write_text("{}")
        if done is not None:
            (jobs / f"{stem}.done").write_text(done)
        if retry_done is not None:
            (jobs / f"{stem}_retry.done").write_text(retry_done)
        if bake_done is not None:
            (jobs / f"{stem}.bake.done").write_text(bake_done)
        if render_done is not None:
            (jobs / f"{stem}.render.done").write_text(render_done)
        return stem

    def _stems(self, engine, jobs):
        return [s for s, _ in engine._jobs_needing_retry(str(jobs))]

    def test_errored_job_included(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, done="error exit 1 ...")
        assert self._stems(engine, jobs) == ["job_0000"]

    def test_clean_done_excluded(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, done="done ...")
        assert self._stems(engine, jobs) == []

    def test_unfinished_job_included(self, engine, tmp_path):
        # Baked but never rendered, no unphased .done (the AutoTest case).
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, bake_done="done ...")          # no .done at all
        assert self._stems(engine, jobs) == ["job_0000"]

    def test_never_started_job_included(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0)                                 # only the .json
        assert self._stems(engine, jobs) == ["job_0000"]

    def test_phased_markers_do_not_count_as_final(self, engine, tmp_path):
        # A render.done error with no unphased .done still needs retry; a pair of
        # successful phased markers without an unphased .done is still unfinished.
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, bake_done="done ...", render_done="error exit 1 ...")
        assert self._stems(engine, jobs) == ["job_0000"]

    def test_successful_retry_clears_earlier_failure(self, engine, tmp_path):
        # Latest attempt wins: orig .done errored, _retry.done succeeded → skip.
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, done="error exit 1 ...", retry_done="done ...")
        assert self._stems(engine, jobs) == []

    def test_failed_retry_overrides_earlier_success(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, done="done ...", retry_done="error exit 1 ...")
        assert self._stems(engine, jobs) == ["job_0000"]

    def test_mixed_batch_sorted_by_index(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 0, done="done ...")               # clean → skip
        self._job(jobs, 1, done="error exit 1 ...")       # failed
        self._job(jobs, 2, bake_done="done ...")          # unfinished
        self._job(jobs, 3, done="done ...")               # clean → skip
        assert self._stems(engine, jobs) == ["job_0001", "job_0002"]

    def test_returns_job_json_path(self, engine, tmp_path):
        jobs = tmp_path / "jobs"; jobs.mkdir()
        self._job(jobs, 7, done="error ...")
        result = engine._jobs_needing_retry(str(jobs))
        assert result[0][1].endswith(os.path.join("jobs", "job_0007.json"))

    def test_missing_dir_returns_empty(self, engine, tmp_path):
        assert engine._jobs_needing_retry(str(tmp_path / "nope")) == []


def test_bt_timing_roundtrip(engine):
    engine._bt_reset_all()
    assert engine._bt("job_start_time") == 0.0
    engine._bt_set("job_start_time", 123.5)
    assert engine._bt("job_start_time") == 123.5
    engine._bt_reset_all()
    assert engine._bt("job_start_time") == 0.0


def test_estim_log_uses_deferred_addon_version(engine, pkg, tmp_path):
    """Exercises the function-local `from . import ADDON_VERSION` deferred import."""
    import json
    engine._estim["output_path"] = str(tmp_path)
    try:
        engine._estim_log({"event": "engine-module-test"})
    finally:
        engine._estim["output_path"] = ""
    rec = json.loads((tmp_path / "estim_log.jsonl").read_text(encoding="utf-8").strip())
    assert rec["addon_version"] == pkg.ADDON_VERSION


def test_retry_path_redirects_console_when_debug_on():
    """TODO-63 Part A: the retry bat (engine.py, runs Blender directly — no launcher)
    must redirect to <retry_stem>.console.log when collect_debug_log is on, else 2>nul."""
    src_path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "BatchSimLab", "engine.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "if s.collect_debug_log:" in src
    assert '.console.log"' in src and '2>&1' in src
    assert '" 2>nul"' in src          # the off-branch tail is retained
    assert "{blender_cmd}{_retry_tail}" in src


class TestEtaTickThrottle:
    """TODO-63 Part B: _log_eta_tick is throttled to >= _ETA_TICK_MIN_SECS, except
    when forced (initial / batch_complete ticks), and records the live ETA figures."""

    def _ticks(self, tmp_path):
        import json
        p = tmp_path / "estim_log.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _call(self, engine, now, force=False):
        return engine._log_eta_tick(
            now=now, elapsed=now, jobs_done=2, total=5, phase="bake",
            remaining_secs=4200.0, job_remaining_secs=600.0, force=force)

    def test_first_tick_then_throttled_then_allowed(self, engine, tmp_path):
        engine._estim["output_path"] = str(tmp_path)
        engine._poll_state["eta_tick_ts"] = 0.0
        try:
            t0 = 100_000.0
            # Forced initial tick (eta_tick_ts armed to 0 at batch_start).
            assert self._call(engine, t0, force=True) is True
            # Within the throttle window — suppressed.
            assert self._call(engine, t0 + engine._ETA_TICK_MIN_SECS - 1) is False
            # Past the window — allowed.
            assert self._call(engine, t0 + engine._ETA_TICK_MIN_SECS + 1) is True
        finally:
            engine._estim["output_path"] = ""
            engine._poll_state["eta_tick_ts"] = 0.0
        ticks = [t for t in self._ticks(tmp_path) if t.get("event") == "batch_eta_tick"]
        assert len(ticks) == 2                       # the throttled call wrote nothing
        assert ticks[0]["remaining_secs"] == 4200.0
        assert ticks[0]["jobs_total"] == 5
        assert ticks[0]["job_remaining_secs"] == 600.0

    def test_force_bypasses_throttle(self, engine, tmp_path):
        engine._estim["output_path"] = str(tmp_path)
        engine._poll_state["eta_tick_ts"] = 0.0
        try:
            assert self._call(engine, 200.0, force=True) is True
            # Immediately again, well inside the window, but forced → still logs.
            assert self._call(engine, 201.0, force=True) is True
        finally:
            engine._estim["output_path"] = ""
            engine._poll_state["eta_tick_ts"] = 0.0
        ticks = [t for t in self._ticks(tmp_path) if t.get("event") == "batch_eta_tick"]
        assert len(ticks) == 2
