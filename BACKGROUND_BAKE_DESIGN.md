# Background-Bake / Render-Once Pipeline — Scoped Design (DRAFT)

Status: **scoping only — not started.** Captures the idea, scope, and open
questions so we can decide later. Resume is explicitly **out of scope** (the
probe proved Mantaflow re-bakes from frame 1 in background too — see
`BUG_TRACKER.md` BUG-010 and memory `background-bake-plan`).

## Why (the wins — all independent of resume)
- **Reliability:** background `bake_all()` is synchronous and never hits the
  windowed save/reload hang (BUG-010 v0.2.32).
- **Speed:** headless bake avoids window/viewport overhead.
- **Fewer crashes:** the glTF/numpy startup crash fires on *every* Blender
  launch (`--factory-startup` does NOT skip glTF — it's bundled). Today = one
  launch per job = N exposures. Two-phase = ~2 launches → far fewer.
- **Cycles can be fully headless** (no window at all). EEVEE still needs a window
  to render.

## Proposed shape
**Phase 1 — bake all jobs in `--background`.** Baking is engine-independent.
One process could loop all jobs (fewest launches) OR one process per job (keeps
crash isolation). Decide based on the crash-vs-isolation trade.

**Phase 2 — render.**
- `render_mode == CYCLES`: render in `--background` too → entire pipeline
  headless, no window ever.
- `render_mode == EEVEE`: render in ONE windowed session looping jobs (pay
  Blender startup once, not N times). Loses per-job process isolation for the
  render phase.

## Open questions / risks to resolve before building
1. **Loop-in-one-process vs process-per-job** for each phase — crash isolation
   vs launch count. (Resume being unavailable means a crashed bake just re-bakes
   from 1 on retry, so isolation matters less than it seems.)
2. **In-session state hygiene** (the big one for a looping render session): reset
   `cache_directory`, `resolution_max`, emitter densities, text objects, frame
   range, render engine/samples between jobs with NO leakage. The worker does
   all this per-process today; in-loop needs careful teardown/setup.
3. **Progress/UI model** becomes two-phase (bake phase, then render phase) — see
   Job Log notes below.
4. **Orchestration**: today one `.bat` runs N launcher calls. New model needs a
   bake `.bat`/pass and a render `.bat`/pass (or one launcher that does both
   phases).
5. **Crash detection** currently keys off per-job `.worker_done` + non-zero exit
   in a one-process-per-job model. A looping process needs per-job sentinels
   written mid-loop and a different "which job was running" recovery story.

## Effort estimate (rough)
Medium. Worker splits into bake-entry and render-entry (or a `--phase` arg);
`export_batch` writes two `.bat` passes; addon poll/Job-Log gains a phase notion.
Reuses existing per-job JSON, cache search, density/text setup, perf logging.

---

## UI changes IF we also remove the RESUME option entirely (NOTES ONLY — do not build)
Context: RESUME currently = (use_existing_cache + partial cache) → merge presave
+ bake (which re-bakes from 1 anyway). "Removing resume" would mean a partial
cache just takes the FULL-bake path; the SKIP path (complete cache) stays.

Things that would need touching (none designed yet):
- **`smoke_worker.py`**: drop the `elif use_existing_cache and baked_frames:`
  RESUME branch + its presave-merge; partial cache falls through to FULL BAKE.
  Keep SKIP (complete cache) and the presave wipe-protection for SKIP.
- **Bake-decision logging**: remove "RESUME — N present, M to bake"; the decision
  becomes SKIP / FULL only.
- **`__init__.py` panel**: `use_existing_cache` checkbox stays (it still drives
  SKIP), but its tooltip says "resume or skip" — reword to just "skip complete
  caches". No new/removed widgets strictly required.
- **Progress bar**: TODO-31 ("101 of 500" on resume) becomes moot — close/reject
  it, since there's no resume to show.
- **Estimation**: `bake_remaining` logic that scaled by remaining-frames for a
  retry (v0.2.28) can simplify (a partial cache → full bake → full estimate).
- **Docs**: README "Use Existing Cache" bullet + TODOS/BUG_TRACKER notes.
- **Tests**: drop/adjust any RESUME-path assertions (e.g.
  `TestWorkerResumeNoReload` stays relevant only while the branch exists).

Net: removing resume is mostly *subtractive* in the worker + a tooltip/doc
reword; no major UI restructure. Revisit if/when we commit to it.
