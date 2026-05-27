# SmokeSimLab — Manual Test Plan (v0.3.0)

> **v0.3.0 re-test note.** Your first pass surfaced **BUG-011**: the bake ignored
> the job frame range and baked the .blend's full range (500 frames for a 1–20
> job) — that's why the Session-A bake bar read "0" (it targeted 20 while the
> count climbed to 500). Fixed in v0.3.0. **Re-export + re-run** before
> re-testing (worker/launcher bumped to 0.3.0). Re-test items:
> - **BUG-011 / BUG-003 bake bar:** after a bake, worker log `Cache data files
>   found: N` must equal the requested count (e.g. 20), and the bake bar reads
>   "N of 20" — not 500.
> - **TODO-22** (the line you didn't see): pid / exit_code / time_to_exit now go
>   to **`debug_log.txt`** + the console — *not* the per-job `.log`. Look there.
> - **`crash_log.txt`** entries now carry a `Blender: <version>` header line; the
>   worker `.log` now opens with a `Blender <version>` line.
> - Still open from your pass: Session B 2nd placeholder run (you marked "?"),
>   Session C run-to-completion + mid-run guard, and the crash path.

Goal: verify everything that needs a real Blender run in as few sessions as
possible. Covers the **new v0.3.0 work** (TODO-25/26/28, TODO-22 diagnostics)
and the **pre-existing `DEPLOYED / UNVERIFIED` bugs** (BUG-001/002/003/004/010).

Most checks piggy-back on a couple of fast batch runs — use a **tiny scene** so
each bake takes seconds, not minutes.

---

## Pre-flight (once)

- [ x] Re-install / reload the **v0.3.0** addon in Blender 5.1.1. Panel header
      should read `SmokeSimLab v0.3.0`.
- [x ] **Re-export the batch** before any run — WORKER/LAUNCHER versions bumped to
      0.3.0, so an old export triggers the version-mismatch warning on Run Batch.
- [x ] Test scene for speed: domain **resolution ≈ 32–48**, frame range **1–20**,
      a flow emitter, the 4 text objects present. Pick a throwaway **Output**
      folder (call it `…/v234_test`).
- [x ] Keep **Collect Debug Log** ON for the whole plan (richer logs + keeps the
      batch console open so you can read it).

> Tip: a 32³ / 20-frame job bakes + renders in well under a minute, so a 2–3 job
> batch is fast to repeat.

---

## Session A — UI gating + bake-only mode
Covers **TODO-25**, **TODO-26**, and starts **BUG-001 / BUG-003**.

**Before exporting (fresh output folder):**
- [x ] **TODO-25:** *Run Batch* button is **greyed out** (no `run_smoke_batch.bat`
      yet). *Monitor Existing Jobs* (Utilities) is also greyed.

**Toggle Render Simulation Result OFF:**
- [x ] **TODO-26:** Unchecking *Render Simulation Result* greys out **Render
      Engine**, **Samples**, and **Display Results When Finished** (and unticks
      Display Results if it was on).

**Export a 2-job sweep (e.g. resolution 32 & 48), bake-only:**
- [x ] *Run Batch* becomes **enabled** right after Export (TODO-25 case 1).
- [x ] Click **Run Batch**. While it runs:
  - [x ] **TODO-28 safeguard:** the *Append/Replace* toggle, **Export Batch**, and
        **Run Batch** are all **greyed out** during the run.
  - [x ] **BUG-001:** every Job Log row keeps its number + name + status icon as
        jobs go IN_PROGRESS → COMPLETE (no blank rows on status change/scroll).
  - [0 ] **BUG-003:** the **bake** progress bar advances (not stuck at "0 of N").
        (No render bar expected in bake-only.)
- [ ] After completion, in the Output folder:
  - [x ] `Cache/<name>/` has VDB frames; `Renders/results.csv` has 2 rows.
  - [x ] **No** `.mp4` and **no** `.png` were produced (bake-only worked).
  - [x ] A job `.log` contains `Render Simulation Result disabled — bake-only run`.
  - [0 ] **TODO-22:** that `.log` ends with a line like
        `Job job_0000 exited: pid=… exit_code=0 time_to_exit=…s`.

---

## Session B — full render reuse: SKIP BAKE + render progress
Covers **BUG-004**, **BUG-003** (render bar incl. the "0 of N" overwrite case),
bake-time sidecar.

- [x ] Re-check **Render Simulation Result**. Enable **Use Existing Cache**.
- [x ] **REPLACE**-export the *same* params as Session A and **Run Batch**.
- [x ] In the job logs / panel, confirm each job logs **SKIP BAKE** (cache from
      Session A is reused).
- [x ] **BUG-004:** the cache is **not wiped** — VDB frame count stays the same and
      the render uses it (mp4 + png now produced). No "Cache dir empty" / full
      rebake.
- [x ] **BUG-003:** the **render** progress bar advances 0 → N as PNGs are written.
- [x ] Bake-time text overlay in the render shows the **original** bake time (from
      `Cache/<name>/bake_time.json`), not "Bake: 0 sec".
- [ ?] Run it a **second time** with **Use Placeholders** on (frames already exist):
      render bar should still show real progress, not freeze at "0 of N"
      (BUG-003 overwrite case).

---

## Session C — Append mode
Covers **TODO-28** (the core fix).

- [x ] **REPLACE**-export job set **X** (e.g. resolution 32). Run to completion.
- [x ] Switch the toggle to **Append**. Change params (e.g. add resolution 64, 96)
      and click **Export Batch**.
- [x ] **Open `run_smoke_batch.bat` in a text editor** and confirm it lists **all**
      jobs — the original job(s) **first**, then the newly appended ones, with
      contiguous `Job k/total` numbering. *(Before v0.3.0 it contained only the
      appended jobs.)*
- [ ] **Run Batch.** The earlier job(s) **SKIP BAKE** (or use placeholders) and the
      new ones bake/render. Every Job Log row ends **COMPLETE** — none left stuck
      at NOT_STARTED (open circle).
- [ ] (Optional) repeat the mid-run guard check from Session A while this runs.

---

## Crash path — BUG-002 + TODO-22 (opportunistic / forced)
Crashes are intermittent (root cause is Blender 5.1.1's glTF/numpy import at
startup — see `project_crash_root_cause`), so verify when one happens, or force
one:

- **Force a "hang/crash":** while a job's Blender window is baking, **kill that
  Blender process** from Task Manager (simulates a crash/hang).
  - [ ] **BUG-002:** the launcher detects it (non-zero exit / stale-log /
        wall-clock), writes a `.crashed` marker, and the batch **moves on** to the
        next job instead of hanging.
  - [ ] The Job Log row shows **CRASHED** (⚠ / ERROR icon) — visually **distinct**
        from a FAILED row (✗ / CANCEL).
  - [ ] **TODO-22:** the job `.log` (or `crash_log.txt`) records
        `time_to_exit=…s` and, on the crash branch, `werfault_poll=…s`. Note both
        numbers — they tell us whether a future stall is Blender running long
        (large `time_to_exit`) vs. the WerFault poll (large `werfault_poll`).
- [ ] If a **real** crash occurs, also check whether `blender.crash.txt` now lands
      in the crash log (TODO-27 v0.2.33 grace period — still unverified).

---

## What to capture for follow-up
If anything looks off, grab these from the Output folder and send them over:
- `jobs/job_*.log` (per-job console) and `jobs/*.crashed` if present
- `debug_log.txt`, `crash_log.txt`, `blender_stderr.txt`
- `run_smoke_batch.bat` (for the Append check)
- A screenshot of the panel mid-run (Job Log + progress bars)

---

## Coverage map

| Item | Status before | Verified by |
|------|---------------|-------------|
| TODO-25 Run Batch gating | new (v0.3.0) | Session A |
| TODO-26 Render Simulation Result | new (v0.3.0) | Session A |
| TODO-28 Append .bat re-list + mid-run guard | new (v0.3.0) | Session C (+ A) |
| TODO-22 crash-timing diagnostics | new (v0.3.0) | Session A (time_to_exit) + Crash path |
| BUG-001 job log blanking | DEPLOYED/UNVERIFIED | Session A |
| BUG-003 render/bake progress bar | DEPLOYED/UNVERIFIED | Sessions A + B |
| BUG-004 SKIP BAKE cache wipe | DEPLOYED/UNVERIFIED | Session B |
| BUG-010 RESUME save/reload | DEPLOYED/UNVERIFIED | (interrupt a bake, re-run w/ Use Existing Cache; check worker log for resume vs re-bake-from-1 and that all frames end present) |
| BUG-002 crash detection | DEPLOYED/UNVERIFIED | Crash path |
