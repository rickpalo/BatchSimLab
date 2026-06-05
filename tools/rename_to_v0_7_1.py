"""rename_to_v0_7_1.py — Migrate pre-v0.7.1 cache + render names to the new format.

v0.7.1 reformatted filenames produced by `make_name()`:
  • Trailing zeros trimmed:    V0.0 -> V0,  A1.0 -> A1,  NS2.0 -> NS2,  etc.
  • Single-char OFF indicator: D-OFF -> Dx,  N-OFF -> Nx
  • v0.7.0 sim params now in the name (default-suppressed)

This script walks an existing batch's output folder and renames the
on-disk Cache/ + Renders/ artefacts to the new format.  By default it
runs as a DRY-RUN — prints every rename it would make without changing
anything.  Pass --apply to actually perform the renames.

USAGE
-----
    python tools/rename_to_v0_7_1.py "<output_path>" [options]

OPTIONS
-------
    --apply             Actually rename (default: dry-run; prints plan only).
    --update-csv        Also rewrite Renders/results.csv `name` column rows.
    --bare-d=MODE       Pre-v0.6.2 `D<N>` names (no `-Slow`/`-Fast` suffix)
                        are ambiguous — could be slow=True or slow=False.
                        MODE = slow -> rename `D5` -> `D5-Slow`
                        MODE = fast -> rename `D5` -> `D5-Fast`
                        MODE = skip -> leave them unchanged (default)
                        Per BUG-013 history most pre-v0.6.2 dissolve jobs
                        were slow=True; if your workflow matches, use
                        `--bare-d=slow`.
    -v, --verbose       Show every directory/file checked, not just renames.

EXAMPLES
--------
    # Dry-run — see what WOULD change for this batch folder.
    python tools/rename_to_v0_7_1.py "E:/.../AutoTest"

    # Actually do it.  Bare D5 names treated as slow=True per BUG-013 history.
    python tools/rename_to_v0_7_1.py "E:/.../AutoTest" --apply --bare-d=slow

    # Full migration including CSV rewrite.
    python tools/rename_to_v0_7_1.py "E:/.../AutoTest" --apply --update-csv --bare-d=slow

WHAT IT TOUCHES
---------------
    <output_path>/Cache/<oldname>/        -> Cache/<newname>/         (directories)
    <output_path>/Renders/<oldname>.png   -> Renders/<newname>.png    (final still)
    <output_path>/Renders/<oldname>.mp4   -> Renders/<newname>.mp4    (playblast)
    <output_path>/Renders/<oldname>_frames/ -> Renders/<newname>_frames/  (PNG seq)
    <output_path>/Renders/results.csv     `name` column (only with --update-csv)

WHAT IT WILL NOT TOUCH
----------------------
    jobs/*  — per-batch ephemera; the next Export Batch regenerates them anyway.
    Any directory/file already in v0.7.1 format (no-op skip).
    Symlinks (followed only via os.path.isdir; not traversed recursively).

SAFETY
------
    • Default mode is dry-run.  Read the printed plan before passing --apply.
    • Two old names that would map to the same new name (collision) are
      reported as a WARNING and skipped, NOT renamed.  Manual intervention
      needed in that case.
    • If the new name already exists on disk (e.g. you've already partially
      migrated), the rename is reported as SKIPPED and not retried.
    • This script does NOT modify the addon's saved settings, only on-disk
      cache/render directories.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from collections import defaultdict

# Windows CMD defaults to cp1252 which can't encode the em-dashes / bullets /
# box-drawing chars used in this script's docstrings + plan output.  Force
# UTF-8 so --help and the plan print cleanly when piped or redirected.
# errors="replace" is a safety net for exotic console code pages.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass  # older Python or non-reconfigurable stream — accept whatever default


# ── _fmt_num: mirror the addon's v0.7.1 trailing-zero trimmer ───────────────
def _fmt_num(s: str) -> str:
    """Convert a numeric component string to the v0.7.1 compact form.

    "0.0" -> "0", "1.0" -> "1", "0.50" -> "0.5", "2.25" -> "2.25"
    """
    try:
        return f"{round(float(s), 3):g}"
    except ValueError:
        return s


# Pattern for a `Letter[s]<number>` filename component (e.g. V0.0, NS2.5, R128).
# The number may be negative or have a decimal point.
_COMPONENT_RE = re.compile(r"^([A-Z][A-Za-z]*?)(-?\d+(?:\.\d+)?)$")

# Bare `D<N>` — pre-v0.6.2 dissolve-on names with no -Slow/-Fast suffix.
_BARE_D_RE = re.compile(r"^D(\d+)$")


def migrate_name(old: str, bare_d_mode: str = "skip") -> tuple[str | None, str]:
    """Translate a single old name to v0.7.1 format.

    Returns
    -------
    (new_name, reason)
        new_name = the rewritten name, or None if no change / can't rename
        reason   = human-readable summary of what changed (or why nothing did)
    """
    if not old:
        return (None, "empty input")

    parts = old.split("_")
    out_parts: list[str] = []
    changes: list[str] = []

    for p in parts:
        # D-OFF / N-OFF -> Dx / Nx
        if p == "D-OFF":
            out_parts.append("Dx")
            changes.append("D-OFF->Dx")
            continue
        if p == "N-OFF":
            out_parts.append("Nx")
            changes.append("N-OFF->Nx")
            continue

        # Bare D<N> — ambiguous pre-v0.6.2 dissolve names.  MUST be checked
        # before _COMPONENT_RE which would otherwise match "D100" as
        # prefix='D' num='100' and bypass the bare-D handling.
        m_bare = _BARE_D_RE.match(p)
        if m_bare:
            n = m_bare.group(1)
            if bare_d_mode == "slow":
                out_parts.append(f"D{n}-Slow")
                changes.append(f"D{n}->D{n}-Slow (bare-d=slow)")
            elif bare_d_mode == "fast":
                out_parts.append(f"D{n}-Fast")
                changes.append(f"D{n}->D{n}-Fast (bare-d=fast)")
            else:  # skip
                return (None, f"ambiguous bare D{n} — pass --bare-d=slow|fast")
            continue

        # Letter<number> with possible trailing zeros (V0.0, NS2.0, etc.)
        m = _COMPONENT_RE.match(p)
        if m:
            prefix, num = m.group(1), m.group(2)
            new_num = _fmt_num(num)
            if num != new_num:
                changes.append(f"{prefix}{num}->{prefix}{new_num}")
            out_parts.append(f"{prefix}{new_num}")
            continue

        # Anything else (e.g. "D5-Slow", "D5-Fast", "F-Y", "BR1.5"): pass through.
        out_parts.append(p)

    new = "_".join(out_parts)
    if new == old:
        return (None, "already in v0.7.1 format")
    return (new, ", ".join(changes))


# ── Filesystem helpers ──────────────────────────────────────────────────────
def _list_cache_dirs(output_path: str) -> list[str]:
    """Return the list of subdirectory names under <output_path>/Cache/."""
    cache_root = os.path.join(output_path, "Cache")
    if not os.path.isdir(cache_root):
        return []
    return sorted(d for d in os.listdir(cache_root)
                  if os.path.isdir(os.path.join(cache_root, d)))


def _list_render_artefacts(output_path: str) -> dict[str, list[str]]:
    """Group everything under <output_path>/Renders/ by their job-stem name.

    Returns a dict mapping each detected job stem to the list of artefact
    paths (relative to Renders/) belonging to that stem:
        <stem>.png       — final still
        <stem>.mp4       — playblast
        <stem>_frames/   — per-frame PNG sequence directory
    """
    renders_root = os.path.join(output_path, "Renders")
    if not os.path.isdir(renders_root):
        return {}
    by_stem: dict[str, list[str]] = defaultdict(list)
    for entry in os.listdir(renders_root):
        full = os.path.join(renders_root, entry)
        if os.path.isdir(full):
            if entry.endswith("_frames"):
                stem = entry[:-len("_frames")]
                by_stem[stem].append(entry)
        elif os.path.isfile(full):
            stem, ext = os.path.splitext(entry)
            if ext.lower() in (".png", ".mp4"):
                by_stem[stem].append(entry)
    return by_stem


# ── Migration plan ──────────────────────────────────────────────────────────
def build_plan(output_path: str, bare_d_mode: str):
    """Build the rename plan for an output folder.

    Returns a dict with:
        cache_renames:    [(old_path, new_path, reason), ...]
        render_renames:   [(old_path, new_path, reason), ...]
        ambiguous_caches: [(name, reason), ...]
        ambiguous_renders:[(name, reason), ...]
        already_ok:       count of items skipped because already in new format
        collisions:       [(new_name, [old_name1, old_name2, ...]), ...]
    """
    plan = {
        "cache_renames":     [],
        "render_renames":    [],
        "ambiguous_caches":  [],
        "ambiguous_renders": [],
        "already_ok":        0,
        "collisions":        [],
    }
    cache_root   = os.path.join(output_path, "Cache")
    renders_root = os.path.join(output_path, "Renders")

    # ── Caches ──────────────────────────────────────────────────────────────
    new_to_old_cache: dict[str, list[str]] = defaultdict(list)
    for old_name in _list_cache_dirs(output_path):
        new_name, reason = migrate_name(old_name, bare_d_mode)
        if new_name is None:
            if reason == "already in v0.7.1 format":
                plan["already_ok"] += 1
            else:
                plan["ambiguous_caches"].append((old_name, reason))
            continue
        new_to_old_cache[new_name].append(old_name)
        old_path = os.path.join(cache_root, old_name)
        new_path = os.path.join(cache_root, new_name)
        plan["cache_renames"].append((old_path, new_path, reason))

    # Detect collisions where two different old names would produce the same new name.
    for new_name, olds in new_to_old_cache.items():
        if len(olds) > 1:
            plan["collisions"].append(
                (os.path.join(cache_root, new_name), olds)
            )

    # ── Renders (group by stem) ─────────────────────────────────────────────
    new_to_old_render: dict[str, list[str]] = defaultdict(list)
    for old_stem, artefacts in _list_render_artefacts(output_path).items():
        new_stem, reason = migrate_name(old_stem, bare_d_mode)
        if new_stem is None:
            if reason == "already in v0.7.1 format":
                plan["already_ok"] += 1
            else:
                plan["ambiguous_renders"].append((old_stem, reason))
            continue
        new_to_old_render[new_stem].append(old_stem)
        for artefact in artefacts:
            old_path = os.path.join(renders_root, artefact)
            new_artefact = artefact.replace(old_stem, new_stem, 1)
            new_path = os.path.join(renders_root, new_artefact)
            plan["render_renames"].append((old_path, new_path, reason))

    for new_stem, olds in new_to_old_render.items():
        if len(olds) > 1:
            plan["collisions"].append(
                (os.path.join(renders_root, new_stem), olds)
            )

    return plan


# ── Apply / print ───────────────────────────────────────────────────────────
def print_plan(plan, verbose=False):
    print(f"\n{'─' * 70}")
    print(f"Migration plan:")
    print(f"{'─' * 70}")
    n_cache  = len(plan["cache_renames"])
    n_render = len(plan["render_renames"])
    n_ambig  = len(plan["ambiguous_caches"]) + len(plan["ambiguous_renders"])
    n_coll   = len(plan["collisions"])
    n_ok     = plan["already_ok"]

    print(f"  Cache renames:      {n_cache}")
    print(f"  Render renames:     {n_render}")
    print(f"  Already in format:  {n_ok}")
    print(f"  Ambiguous (skip):   {n_ambig}")
    print(f"  Name collisions:    {n_coll}")

    if plan["cache_renames"]:
        print("\nCache dirs to rename:")
        for old, new, reason in plan["cache_renames"]:
            print(f"  {os.path.basename(old)}")
            print(f"    -> {os.path.basename(new)}")
            print(f"    ({reason})")

    if plan["render_renames"]:
        print("\nRender artefacts to rename:")
        for old, new, reason in plan["render_renames"]:
            print(f"  {os.path.basename(old)}")
            print(f"    -> {os.path.basename(new)}")
            if verbose:
                print(f"    ({reason})")

    if plan["ambiguous_caches"] or plan["ambiguous_renders"]:
        print("\nAMBIGUOUS (not renamed):")
        for name, reason in plan["ambiguous_caches"]:
            print(f"  Cache/{name}  — {reason}")
        for name, reason in plan["ambiguous_renders"]:
            print(f"  Renders/{name}  — {reason}")

    if plan["collisions"]:
        print("\nCOLLISIONS (skipped — two old names would produce the same new name):")
        for new_path, olds in plan["collisions"]:
            print(f"  Would-be: {new_path}")
            for old in olds:
                print(f"    from: {old}")
        print("  -> Inspect manually and merge/delete the old dirs before re-running.")


def apply_plan(plan):
    """Execute the renames in the plan.  Returns (successes, failures)."""
    successes = 0
    failures: list[tuple[str, str, str]] = []
    # Skip anything that's part of a collision — we already reported these.
    coll_news = {new_path for new_path, _ in plan["collisions"]}

    # Apply cache renames first, then render renames.  Order within each
    # group doesn't matter because old and new names are distinct.
    for old, new, _reason in plan["cache_renames"] + plan["render_renames"]:
        if new in coll_news:
            continue
        if os.path.exists(new):
            failures.append((old, new, "target already exists"))
            continue
        try:
            os.rename(old, new)
            successes += 1
            print(f"  ✓ {os.path.basename(old)} -> {os.path.basename(new)}")
        except OSError as e:
            failures.append((old, new, str(e)))
            print(f"  ✗ {os.path.basename(old)} ({e})")
    return successes, failures


def update_csv(output_path: str, bare_d_mode: str, dry_run: bool):
    """Rewrite the `name` column of Renders/results.csv to the v0.7.1 format."""
    csv_path = os.path.join(output_path, "Renders", "results.csv")
    if not os.path.isfile(csv_path):
        print(f"  (no results.csv found at {csv_path})")
        return 0
    with open(csv_path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return 0
    header, *data = rows
    if "name" not in header:
        print("  (results.csv has no 'name' column; skipping)")
        return 0
    name_idx = header.index("name")

    updated = 0
    for row in data:
        if name_idx >= len(row):
            continue
        old = row[name_idx]
        new, _reason = migrate_name(old, bare_d_mode)
        if new is not None:
            print(f"  CSV: {old}")
            print(f"    -> {new}")
            row[name_idx] = new
            updated += 1

    if updated and not dry_run:
        # Write to a temp file then atomic-replace (no partial writes).
        tmp_path = csv_path + ".tmp_v0_7_1"
        with open(tmp_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(data)
        os.replace(tmp_path, csv_path)
        print(f"  ✓ results.csv rewritten ({updated} row(s) updated)")
    elif updated:
        print(f"  (dry-run) would update {updated} row(s)")
    else:
        print("  (no CSV rows needed updating)")
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Migrate pre-v0.7.1 cache + render names to v0.7.1 format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("EXAMPLES")[1].rstrip(),
    )
    parser.add_argument("output_path",
                        help="Batch output folder containing Cache/ and/or Renders/")
    parser.add_argument("--apply", action="store_true",
                        help="Actually rename (default: dry-run prints plan only)")
    parser.add_argument("--update-csv", action="store_true",
                        help="Also rewrite Renders/results.csv 'name' column")
    parser.add_argument("--bare-d", choices=["slow", "fast", "skip"], default="skip",
                        help="Handle ambiguous bare D<N> names (default: skip)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    output_path = os.path.abspath(args.output_path)
    if not os.path.isdir(output_path):
        print(f"ERROR: not a directory: {output_path}", file=sys.stderr)
        sys.exit(1)

    has_cache   = os.path.isdir(os.path.join(output_path, "Cache"))
    has_renders = os.path.isdir(os.path.join(output_path, "Renders"))
    if not (has_cache or has_renders):
        print(f"ERROR: neither Cache/ nor Renders/ found under {output_path}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {output_path}")
    print(f"Mode:     {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"bare-d:   {args.bare_d}")

    plan = build_plan(output_path, args.bare_d)
    print_plan(plan, verbose=args.verbose)

    if not args.apply:
        print(f"\n{'─' * 70}")
        print("DRY-RUN — no files modified.  Re-run with --apply to perform renames.")
        if args.update_csv:
            print("--update-csv was set but takes effect only with --apply.")
        print(f"{'─' * 70}")
        return

    if not (plan["cache_renames"] or plan["render_renames"]) and not args.update_csv:
        print("\nNothing to do.")
        return

    print(f"\n{'─' * 70}")
    print("Applying renames:")
    print(f"{'─' * 70}")
    ok, failed = apply_plan(plan)
    print(f"\n  Succeeded: {ok}")
    if failed:
        print(f"  Failed:    {len(failed)}")
        for old, new, err in failed:
            print(f"    • {os.path.basename(old)} -> {os.path.basename(new)}: {err}")

    if args.update_csv:
        print(f"\n{'─' * 70}")
        print("Updating results.csv:")
        print(f"{'─' * 70}")
        update_csv(output_path, args.bare_d, dry_run=False)


if __name__ == "__main__":
    main()
