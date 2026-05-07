# SmokeSimLab — Pending Issues

Items to address once file synchronization catches up (~5,000 PNGs behind as of 2026-05-06).

---

## TODO-1: Crash log written to jobs folder (gets deleted on next export)

**Current behaviour:**  
`smoke_launcher.py` copies `%TEMP%\blender.crash.txt` into  
`<output_path>/jobs/<job_stem>_crash_<YYYYMMDD_HHMMSS>.txt`

**Problem:**  
The `jobs/` directory is wiped by `export_batch` before every run, so crash logs
from earlier batches are silently lost.

**Desired behaviour:**  
- Single append-only file at `<output_path>/crash_log.txt` (survives re-exports).
- Each crash appends a dated header block followed by the contents of
  `blender.crash.txt`, e.g.:

```
=== 2026-05-06 14:23:11  job_0003_res128_v1.0_a1.0 ===
<contents of blender.crash.txt>
```

- Still write the per-job `<job_stem>.crashed` marker in `jobs/` (used by the
  batch runner to detect failures) — that file is intentionally ephemeral.

**Files to change:** `scripts/SmokeSimLab/smoke_launcher.py` (`_save_crash_log`).

---

## TODO-2: Retry job does not find partial bake cache from crashed job

**Observed behaviour:**  
A job crashed approximately halfway through baking.  The crash was correctly
detected and the `.crashed` marker was written.  When the batch was retried
(`auto_retry_failed` or manual retry), the retry job reported no existing cache
and started a full rebake from frame 1, discarding the ~50% already baked.

**Expected behaviour:**  
The retry should detect the partial VDB cache and resume baking from the last
good frame (this is what `use_existing_cache=True` + `cache_resumable=True`
is designed to do).

**Likely root causes to investigate:**
1. Cache directory name mismatch between the original job and the retry job —
   `make_name()` appends a run index; if the retry produces a different name
   the cache lookup misses entirely.
2. The worker's cache completeness check uses `frame_start`…`frame_end`; if the
   crash left the cache directory in a partially-written state the check may
   return "no cache" rather than "partial cache".
3. Confirm `d.cache_resumable = True` is actually being set before `bake_all()`
   on the retry path (check worker log for the "Resumable cache enabled" line).

**Files to investigate:** `scripts/SmokeSimLab/smoke_worker.py` (bake logic,
cache completeness check), `scripts/SmokeSimLab/__init__.py` (`make_name`,
`SMOKE_OT_retry_failed`).

---

## TODO-3: "Utilities" collapsible section at bottom of panel

**Desired behaviour:**  
Add a new collapsible box at the very bottom of `SMOKE_PT_panel.draw`, below all
existing sections, labelled **Utilities**.  Default collapsed.

Inside the expanded section, two checkboxes (both default `False`):

| Property | Label | Behaviour |
|---|---|---|
| `collect_crash_logs` | Collect crash logs | When checked, `smoke_launcher.py` writes the append-only `crash_log.txt` (see TODO-1). When unchecked, crash logging is skipped. |
| `collect_estimation_data` | Collect estimation data | When checked, the polling timer writes `estim_log.jsonl` (already implemented). When unchecked, `_estim_log` is a no-op. Also controls whether `perf_log.json` is written by the worker. |

**Implementation notes:**
- Add `collect_crash_logs: bpy.props.BoolProperty(default=False)` and
  `collect_estimation_data: bpy.props.BoolProperty(default=False)` to
  `SmokeSettings`.
- Pass `collect_crash_logs` in the job JSON so `smoke_launcher.py` can read it.
- Pass `collect_estimation_data` in the job JSON so `smoke_worker.py` can gate
  `perf_log.json` writes.
- Gate `_estim_log` writes in `_poll_batch_progress` on
  `s.collect_estimation_data`.
- The `show_utilities` BoolProperty drives the collapsible header (same pattern
  as `show_setup`, `show_sim_params`, etc.).

**Files to change:** `scripts/SmokeSimLab/__init__.py` (properties + panel draw
+ polling gate), `scripts/SmokeSimLab/smoke_launcher.py` (crash log gate),
`scripts/SmokeSimLab/smoke_worker.py` (perf_log gate).

---

## TODO-4: Update default parameter values

Change the `default=` values on the following `SmokeSettings` properties in
`scripts/SmokeSimLab/__init__.py`:

| Property | New default |
|---|---|
| `resolution` | `64` |
| `buoyancy_density` | `1.0` |
| `heat` | `1.0` |
| `vorticity` | `0.0` |
| `dissolve_speed` (or equivalent dissolve frames property) | `5` |
| `upres` | `2` |
| `noise_strength` | `2.0` |
| `noise_scale` | `2.0` |

**Note:** Verify the exact property names against `SmokeSettings` in `__init__.py`
before changing — the table above uses likely names, not confirmed names.

**Files to change:** `scripts/SmokeSimLab/__init__.py` (`SmokeSettings` property
declarations).
