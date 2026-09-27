#!/usr/bin/env python3
"""
Coverage ratchet for the Rust workspace.

Compares current line coverage (from an lcov file produced e.g. by
`cargo llvm-cov --lcov`) against a committed baseline stored in
`coverage/coverage-ratchet.json`.  The ratchet:

* **fails the build** when line coverage on a tracked file (or overall) is
  *lower* than the committed baseline,
* **fails the build** when a tracked file disappears from the current run
  (e.g. a test file was deleted without re-baselining),
* **fails the build** when the baseline itself is unpopulated
  (`overall` is null or `files` is empty) — an empty baseline ratchets
  nothing, so it must never pass silently,
* **passes** when coverage is equal or higher,
* **records new values** when run with `--update-baseline` (write the new
  values back to the baseline so they become the new floor).

Baseline JSON schema (`coverage/coverage-ratchet.json`)::

    {
      "overall": {"covered": 0, "total": 0},
      "files": {
        "contracts/raffle-instance/src/lib.rs": {"covered": 0, "total": 0}
      }
    }

Usage:
    python scripts/check_coverage_ratchet.py --lcov coverage/lcov.info \
        --baseline coverage/coverage-ratchet.json [--update-baseline]

    # Raise/reset the floor explicitly and commit the diff in the same PR:
    python scripts/check_coverage_ratchet.py --lcov coverage/lcov.info \
        --baseline coverage/coverage-ratchet.json --update-baseline
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_lcov(lcov_path):
    """Return {relative_file_path: {"covered": int, "total": int}}."""
    files = {}
    current = None
    with open(lcov_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                raw = line[3:].strip()
                rel = Path(raw)
                try:
                    rel = rel.relative_to(REPO_ROOT)
                except ValueError:
                    pass
                current = rel.as_posix()
                files.setdefault(current, {"covered": 0, "total": 0})
            elif line.startswith("LF:"):
                files[current]["total"] = int(line[3:])
            elif line.startswith("LH:"):
                files[current]["covered"] = int(line[3:])
    return files


def pct(covered, total):
    if total <= 0:
        return None
    return (covered / total) * 100.0


def fmt_pct(value):
    return f"{value:.2f}%"


def load_baseline(path):
    if not path.exists():
        return {"overall": None, "files": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lcov", required=True, help="Path to lcov info file")
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON")
    parser.add_argument(
        "--update",
        dest="update_baseline",
        action="store_true",
        help="Write current coverage back to the baseline file (deprecated alias)",
    )
    parser.add_argument(
        "--update-baseline",
        dest="update_baseline",
        action="store_true",
        help="Write current coverage back to the baseline file",
    )
    args = parser.parse_args()

    lcov_path = Path(args.lcov)
    baseline_path = Path(args.baseline)
    if not lcov_path.exists():
        print(f"Error: lcov file not found: {lcov_path}", file=sys.stderr)
        sys.exit(2)

    current = parse_lcov(lcov_path)
    total_covered = sum(v["covered"] for v in current.values())
    total_lines = sum(v["total"] for v in current.values())

    baseline = load_baseline(baseline_path)
    baseline_files = baseline.get("files") or {}
    baseline_overall = baseline.get("overall")

    regressions = []
    errors = []

    baseline_empty = not baseline_files or baseline_overall is None
    if baseline_empty:
        errors.append(
            "No committed coverage baseline (overall is null or files is empty) — "
            "the ratchet enforces nothing. Run with --update-baseline on a clean "
            "workspace result and commit the generated baseline to arm it."
        )
    else:
        for file, base in sorted(baseline_files.items()):
            cur = current.get(file)
            if cur is None or cur["total"] <= 0:
                regressions.append(
                    f"  {file}: missing from current coverage run "
                    "(test file deleted without re-baselining?)"
                )
                continue
            base_pct = pct(base["covered"], base["total"])
            cur_pct = pct(cur["covered"], cur["total"])
            if base_pct is not None and cur_pct is not None:
                if cur_pct + 1e-9 < base_pct:
                    regressions.append(
                        f"  {file}: {fmt_pct(cur_pct)} (was {fmt_pct(base_pct)})"
                    )
        if baseline_overall is not None and total_lines > 0:
            ob = pct(baseline_overall["covered"], baseline_overall["total"])
            oc = pct(total_covered, total_lines)
            if ob is not None and oc is not None and oc + 1e-9 < ob:
                regressions.append(
                    f"  overall: {fmt_pct(oc)} (was {fmt_pct(ob)})"
                )

    print(f"Line coverage: {fmt_pct(pct(total_covered, total_lines))} "
          f"({total_covered}/{total_lines} lines, {len(current)} files)")

    newly_covered = sum(1 for f in current if f not in baseline_files and current[f]["total"] > 0)
    if newly_covered:
        print(f"{newly_covered} tracked file(s) without a baseline (adopted on --update-baseline).")

    if args.update_baseline:
        next_overall = {"covered": total_covered, "total": total_lines}
        next_files = {}
        for file in sorted(current):
            if current[file]["total"] > 0:
                next_files[file] = current[file]
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {"overall": next_overall, "files": next_files},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Updated baseline: {baseline_path}")

    if errors and not args.update_baseline:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if regressions:
        print("ERROR: coverage regression detected:", file=sys.stderr)
        for r in regressions:
            print(r, file=sys.stderr)
        sys.exit(1)

    print("Coverage ratchet: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()