#!/usr/bin/env python3
"""pipeline_bench.py — wall-clock viability test for waterfall bake+render.

Question this answers
----------------------
Mantaflow's bake is already OpenMP-parallel across all cores, so running whole
jobs in parallel just makes CPU-bound bakes time-slice.  The *plausible* win is a
**waterfall**: overlap the GPU-bound render of job N with the CPU-bound bake of
job N+1.  This script measures total wall-clock (first bake start -> last render
end) for two scheduling strategies, for BOTH render engines, and prints a 2x2:

      |  SEQ  | PIPE
  ----+-------+------
  EEVEE |  A  |  B      <- waterfall win = B/A
  CYCLES|  C  |  D      <- waterfall win = D/C

Why both engines: the waterfall only pays when the render is long + GPU-bound.
EEVEE render is short (rasterised) -> small overlap -> expect a small win.
Cycles-GPU render is long (path-traced) -> big overlap -> expect the biggest win.
The recommendation can flip between engines, so measuring both is the point.

No addon code is touched.  It reuses `smoke_worker.py` exactly as production does
(the worker already supports `--phase bake|render|both`), so this is a pure
orchestration experiment, not a fork.

  Strategy SEQ  (baseline):  job0 both ; job1 both ; ... (one process at a time)
  Strategy PIPE (waterfall): bake0 ;
                             loop i: render(i-1) || bake(i)  (concurrent, wait both)
                             render(last)

Engine launch flags (IMPORTANT — from smoke_worker.py)
------------------------------------------------------
* CYCLES runs under --background and auto-selects GPU (OptiX>CUDA>HIP, CPU fallback).
* EEVEE needs an OpenGL context that --background does NOT provide; the worker
  falls back to Cycles otherwise.  So EEVEE is launched with --window-geometry
  (a tiny throwaway window), exactly as the production export does.

Isolation
---------
Each engine renders into its OWN output tree (e:/tmp/pipeline_bench/<engine>/),
with its own Cache/Renders/jobs, so the live AutoTest data is never touched and
the two engines never collide.  Each cell bakes from scratch (cache wiped before
SEQ and before PIPE) so every cell is an honest end-to-end batch.

Usage
-----
  python tools/pipeline_bench.py --prepare              # stage trimmed jobs (both engines)
  python tools/pipeline_bench.py                         # run full A/B/C/D + matrix
  python tools/pipeline_bench.py --engines cycles        # one engine only
  python tools/pipeline_bench.py --run pipe              # one strategy only

Refuses to run while another blender.exe is alive (would poison timings); pass
--force to override.  Progress bars / ETA deliberately ignored — only totals.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

# --- configuration -----------------------------------------------------------

BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
BLEND = (
    r"E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto"
    r"\SmokeSimulatorForPiazzoSanMarco.blend"
)
AUTOTEST = (
    r"E:\BlenderSync\SynologyDrive\ImageOfTheMonth\2018\November - Canaletto"
    r"\smokeTesting\AutoTest"
)
WORKER = os.path.join(AUTOTEST, "smoke_worker.py")
SRC_JOBS_DIR = os.path.join(AUTOTEST, "jobs")

# Source job JSONs to clone (4 DISTINCT real retry jobs: R128 N1, R128 noise-off,
# R128 dissolve+noise-off, R64 — a realistic spread of bake/render costs).
SRC_JOBS = [
    "job_0010_retry.json",
    "job_0014_retry.json",
    "job_0017_retry.json",
    "job_0018_retry.json",
]

SCRATCH = r"e:\tmp\pipeline_bench"

# Trim for a fast viability read (user choice: quick 4 trimmed jobs).
TRIM_FRAME_END = 60

# Engines to test and their launch flags. EEVEE needs a (tiny) window for its GL
# context; CYCLES is happy headless.  Samples: None = keep the source job's value
# (faithful to the real sweep, currently 2); set an int to override.
ENGINES = ["EEVEE", "CYCLES"]
ENGINE_FLAGS = {
    "EEVEE":  ["--window-geometry", "0", "0", "100", "100"],
    "CYCLES": ["--background"],
}
ENGINE_SAMPLES = {
    "EEVEE":  None,
    "CYCLES": None,
}


# --- paths --------------------------------------------------------------------

def engine_dir(engine):
    return os.path.join(SCRATCH, engine.lower())


def engine_jobs_dir(engine):
    return os.path.join(engine_dir(engine), "jobs")


def scratch_job_paths(engine):
    return [
        os.path.join(engine_jobs_dir(engine), f"bench_{i:02d}.json")
        for i in range(len(SRC_JOBS))
    ]


# --- job preparation ----------------------------------------------------------

def prepare_jobs(engine):
    """Clone SRC_JOBS into the engine's scratch tree, trimmed + repointed."""
    jobs_dir = engine_jobs_dir(engine)
    os.makedirs(jobs_dir, exist_ok=True)
    prepared = []
    for i, src_name in enumerate(SRC_JOBS):
        with open(os.path.join(SRC_JOBS_DIR, src_name), "r", encoding="utf-8") as f:
            cfg = json.load(f)

        cfg["frame_start"] = 1
        cfg["frame_end"] = TRIM_FRAME_END
        cfg["output_path"] = engine_dir(engine) + os.sep
        cfg["render_mode"] = engine
        if ENGINE_SAMPLES.get(engine) is not None:
            cfg["render_samples"] = ENGINE_SAMPLES[engine]
        # Force a real first-time bake every run (we also wipe the cache between
        # strategies; this guards against a stray cache hit).
        cfg["use_existing_cache"] = False
        # Unique name per slot -> unique Cache/<name> + Renders/<name>_frames so
        # the source set's duplicate names can't make concurrent bake(i)/
        # render(i-1) collide on the same cache.
        cfg["name"] = f"bench{i:02d}_{cfg['name']}"

        stem = f"bench_{i:02d}"
        dst_path = os.path.join(jobs_dir, stem + ".json")
        cfg["log_path"] = os.path.join(jobs_dir, stem + ".log")
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        prepared.append(dst_path)
        print(f"  [{engine}] prepared {stem}.json  (frames 1-{TRIM_FRAME_END}, "
              f"samples={cfg.get('render_samples')}, name={cfg['name']})")
    return prepared


# --- cleanup between strategies -----------------------------------------------

def _reset_cache_and_markers(engine):
    """Wipe this engine's baked cache, renders, and per-job markers so the next
    strategy bakes from scratch.  Leaves the trimmed job JSONs in place."""
    for sub in ("Cache", "Renders"):
        p = os.path.join(engine_dir(engine), sub)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    jobs_dir = engine_jobs_dir(engine)
    if os.path.isdir(jobs_dir):
        for fn in os.listdir(jobs_dir):
            if fn.endswith((".done", ".worker_done", ".log", ".crashed")):
                try:
                    os.remove(os.path.join(jobs_dir, fn))
                except OSError:
                    pass


# --- worker invocation --------------------------------------------------------

def _cmd(job_path, phase, engine):
    return [
        BLENDER, BLEND, *ENGINE_FLAGS[engine], "--factory-startup",
        "--python", WORKER, "--", job_path, "--phase", phase,
    ]


def _spawn(job_path, phase, engine):
    """Launch one Blender worker process (non-blocking)."""
    return subprocess.Popen(_cmd(job_path, phase, engine),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _run_blocking(job_path, phase, engine, label):
    t0 = time.monotonic()
    rc = subprocess.run(_cmd(job_path, phase, engine),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL).returncode
    dt = time.monotonic() - t0
    print(f"    {label:<26} rc={rc:<3} {dt:7.1f}s")
    return dt


# --- strategies ---------------------------------------------------------------

def run_sequential(jobs, engine):
    print(f"[{engine} SEQ] sequential baseline (each job --phase both)")
    _reset_cache_and_markers(engine)
    t0 = time.monotonic()
    for i, jp in enumerate(jobs):
        _run_blocking(jp, "both", engine, f"job{i} both")
    total = time.monotonic() - t0
    print(f"[{engine} SEQ] TOTAL wall: {total:.1f}s")
    return total


def run_pipeline(jobs, engine):
    print(f"[{engine} PIPE] waterfall (render(i-1) overlaps bake(i))")
    _reset_cache_and_markers(engine)
    t0 = time.monotonic()

    # Prime the pipe: bake job 0.
    _run_blocking(jobs[0], "bake", engine, "job0 bake")

    for i in range(1, len(jobs)):
        ts = time.monotonic()
        pr = _spawn(jobs[i - 1], "render", engine)   # GPU-bound
        pb = _spawn(jobs[i], "bake", engine)          # CPU-bound
        rc_r = pr.wait()
        rc_b = pb.wait()
        print(f"    stage {i:<2} render(job{i-1}) rc={rc_r} || "
              f"bake(job{i}) rc={rc_b}   {time.monotonic()-ts:7.1f}s")

    # Drain: render the final job.
    _run_blocking(jobs[-1], "render", engine, f"job{len(jobs)-1} render")

    total = time.monotonic() - t0
    print(f"[{engine} PIPE] TOTAL wall: {total:.1f}s")
    return total


# --- safety -------------------------------------------------------------------

def _blender_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe"],
                             capture_output=True, text=True).stdout.lower()
        return "blender.exe" in out
    except Exception:
        return False


# --- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prepare", action="store_true",
                    help="(re)generate the trimmed scratch job JSONs and exit")
    ap.add_argument("--engines", default="eevee,cycles",
                    help="comma list of engines to test (default: eevee,cycles)")
    ap.add_argument("--run", choices=["seq", "pipe", "both"], default="both",
                    help="which strategy to run per engine (default: both)")
    ap.add_argument("--force", action="store_true",
                    help="run even if another blender.exe is alive")
    args = ap.parse_args()

    engines = [e.strip().upper() for e in args.engines.split(",") if e.strip()]
    bad = [e for e in engines if e not in ENGINES]
    if bad:
        sys.exit(f"Unknown engine(s): {bad}. Choose from {ENGINES}.")

    if args.prepare:
        for engine in engines:
            print(f"Preparing scratch jobs for {engine} in {engine_jobs_dir(engine)}")
            prepare_jobs(engine)
        return

    # Ensure jobs are staged for every engine we'll run.
    jobs_by_engine = {}
    for engine in engines:
        paths = scratch_job_paths(engine)
        if not all(os.path.exists(p) for p in paths):
            print(f"[{engine}] scratch jobs missing — preparing now.")
            prepare_jobs(engine)
        jobs_by_engine[engine] = paths

    if _blender_running() and not args.force:
        sys.exit("REFUSING: a blender.exe is already running (live sweep?). "
                 "Timings would be invalid. Re-run with --force to override.")

    # results[(engine, strategy)] = seconds
    results = {}
    for engine in engines:
        jobs = jobs_by_engine[engine]
        if args.run in ("seq", "both"):
            results[(engine, "SEQ")] = run_sequential(jobs, engine)
        if args.run in ("pipe", "both"):
            results[(engine, "PIPE")] = run_pipeline(jobs, engine)

    # ---- matrix -------------------------------------------------------------
    print("\n========================= RESULT (wall-clock) =========================")
    print(f"  {'engine':<8} {'SEQ':>10} {'PIPE':>10} {'waterfall win':>16}")
    print("  " + "-" * 50)
    for engine in engines:
        seq = results.get((engine, "SEQ"))
        pipe = results.get((engine, "PIPE"))
        seq_s = f"{seq:8.1f}s" if seq is not None else "    --  "
        pipe_s = f"{pipe:8.1f}s" if pipe is not None else "    --  "
        if seq and pipe:
            win = f"{seq/pipe:.2f}x ({(1-pipe/seq)*100:+.0f}%)"
        else:
            win = "--"
        print(f"  {engine:<8} {seq_s:>10} {pipe_s:>10} {win:>16}")
    print("=======================================================================")
    print("  waterfall win = SEQ/PIPE  (>1.0 means the pipeline was faster)")


if __name__ == "__main__":
    main()
