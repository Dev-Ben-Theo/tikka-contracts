#!/usr/bin/env python3
"""Record WASM sizes and fail when a contract exceeds hard limit or baseline tolerance.

The WASM target directory is defined in exactly one place:
``WASM_TARGET`` in ``scripts/common.sh``. This script reads it from there
(``--wasm-dir`` overrides for local experiments), so
``baselines/wasm_sizes.json`` only records the artifact file name, the hard
limit, and the committed baseline — never a target path (#1011).

An unpopulated baseline (``baseline_bytes`` of 0 or missing) is a build
error, not a silent pass (#1012). Refresh the committed baseline
deliberately after a size-affecting change with::

    stellar contract build
    python3 scripts/check_wasm_sizes.py --update-baseline

and commit the resulting ``baselines/wasm_sizes.json`` diff in the same PR
(see CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "baselines" / "wasm_sizes.json"
COMMON_SH = ROOT / "scripts" / "common.sh"


def wasm_dir_from_common_sh() -> Path:
    """Derive ``target/<WASM_TARGET>/release`` from scripts/common.sh."""
    text = COMMON_SH.read_text(encoding="utf-8")
    match = re.search(r'^WASM_TARGET="([^"]+)"', text, re.MULTILINE)
    if not match:
        print(f"ERROR: WASM_TARGET not found in {COMMON_SH}", file=sys.stderr)
        sys.exit(2)
    return ROOT / "target" / match.group(1) / "release"


def artifact_path(wasm_dir: Path, name: str, spec: dict) -> Path:
    # New schema (#1011): only the file name is recorded; the directory
    # comes from scripts/common.sh. The legacy full "path" is still
    # honoured if present so old checkouts keep working.
    if "artifact" in spec:
        return wasm_dir / spec["artifact"]
    return ROOT / spec["path"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        default=str(BASELINE_PATH),
        help="Path to baselines/wasm_sizes.json",
    )
    parser.add_argument(
        "--wasm-dir",
        default=None,
        help="Override the WASM output dir (default: derived from scripts/common.sh)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write current sizes back to the baseline file",
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    tolerance = int(baseline.get("tolerance_bytes", 2048))
    wasm_dir = Path(args.wasm_dir) if args.wasm_dir else wasm_dir_from_common_sh()
    report_path = os.environ.get("WASM_SIZE_REPORT", "")
    lines: list[str] = []
    failed = False
    sizes: dict[str, int] = {}

    for name, spec in baseline["contracts"].items():
        wasm_path = artifact_path(wasm_dir, name, spec)
        max_bytes = int(spec["max_bytes"])
        recorded = int(spec.get("baseline_bytes", 0))

        if recorded <= 0:
            print(
                f"ERROR: {name} has no populated baseline (baseline_bytes={recorded}). "
                "Run 'python3 scripts/check_wasm_sizes.py --update-baseline' "
                "after 'stellar contract build' and commit the result.",
                file=sys.stderr,
            )
            failed = True

        if not wasm_path.exists():
            print(f"ERROR: missing {wasm_path}", file=sys.stderr)
            failed = True
            continue

        size = wasm_path.stat().st_size
        sizes[name] = size
        delta = size - recorded if recorded > 0 else 0
        line = f"{name}: {size} bytes"
        if recorded > 0:
            line += f" (baseline {recorded}, delta {delta:+d})"
            if abs(delta) > tolerance:
                print(
                    f"ERROR: {name} size delta {delta:+d} exceeds tolerance {tolerance} bytes",
                    file=sys.stderr,
                )
                failed = True
        if size > max_bytes:
            print(
                f"ERROR: {name} exceeds hard limit ({size} > {max_bytes})",
                file=sys.stderr,
            )
            failed = True
        print(line)
        lines.append(line)

    if args.update_baseline and sizes:
        for name, size in sizes.items():
            baseline["contracts"][name]["baseline_bytes"] = size
        baseline_path.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Updated baseline: {baseline_path}")

    if report_path:
        Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
