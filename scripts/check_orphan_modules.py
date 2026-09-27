#!/usr/bin/env python3
"""
Check for orphaned Rust modules.

This script walks through each crate's src/ directory, resolves the module tree
from lib.rs (and main.rs if present), and reports any .rs files that are not
reachable from the module declarations.

It also flags stray .rs files outside any crate's src/ directory, with an allowlist
for legitimate cases such as build.rs.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Set, Tuple

# Allowlist for .rs files that are legitimately outside crate src/ directories
ALLOWLISTED_ROOT_FILES = {
    "build.rs",
}

# Directories to skip (not crates)
SKIP_DIRS = {
    "target",
    "fuzz",
    ".git",
}


def extract_mod_declarations(file_path: Path) -> Set[str]:
    """Extract module declarations from a Rust source file."""
    mods = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Match mod foo; and mod foo { ... } declarations (including pub mod)
            # Skip comments and strings
            for line in content.split("\n"):
                line = line.strip()
                # Skip comments
                if line.startswith("//") or line.startswith("/*"):
                    continue
                # Match mod declarations (with optional pub)
                match = re.match(r"(?:pub\s*)?mod\s+(\w+)\s*(?:{|;)", line)
                if match:
                    mods.add(match.group(1))
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
    return mods


def resolve_module_tree(
    crate_root: Path, visited: Set[Path] = None
) -> Set[Path]:
    """Recursively resolve all reachable module files from the crate root."""
    if visited is None:
        visited = set()

    if crate_root in visited:
        return set()
    visited.add(crate_root)

    reachable_files = set()
    reachable_files.add(crate_root)

    # Extract mod declarations from this file
    mods = extract_mod_declarations(crate_root)

    for mod_name in mods:
        # Check for mod_name.rs and mod_name/mod.rs
        mod_rs = crate_root.parent / f"{mod_name}.rs"
        mod_dir = crate_root.parent / mod_name / "mod.rs"

        if mod_rs.exists():
            reachable_files.add(mod_rs)
            reachable_files.update(resolve_module_tree(mod_rs, visited))
        elif mod_dir.exists():
            reachable_files.add(mod_dir)
            reachable_files.update(resolve_module_tree(mod_dir, visited))

    return reachable_files


def find_crates(repo_root: Path) -> Dict[Path, Path]:
    """Find all crates by looking for Cargo.toml files."""
    crates = {}
    for cargo_toml in repo_root.rglob("Cargo.toml"):
        # Skip if in target or other skip directories
        if any(skip_dir in cargo_toml.parts for skip_dir in SKIP_DIRS):
            continue
        crate_dir = cargo_toml.parent
        src_dir = crate_dir / "src"
        if src_dir.exists():
            lib_rs = src_dir / "lib.rs"
            main_rs = src_dir / "main.rs"
            if lib_rs.exists():
                crates[cargo_toml] = lib_rs
            elif main_rs.exists():
                crates[cargo_toml] = main_rs
    return crates


def check_crate(crate_root: Path) -> Tuple[Set[Path], Set[Path]]:
    """Check a single crate for orphaned modules."""
    src_dir = crate_root.parent
    all_rs_files = set(src_dir.rglob("*.rs"))

    reachable = resolve_module_tree(crate_root)
    orphans = all_rs_files - reachable

    # Filter out test files (they're conditionally compiled)
    orphans = {f for f in orphans if not f.name.endswith("_test.rs")}

    return reachable, orphans


def check_stray_files(repo_root: Path) -> Set[Path]:
    """Check for stray .rs files outside crate src/ directories."""
    stray_files = set()

    # Find all .rs files in repo root
    for rs_file in repo_root.glob("*.rs"):
        if rs_file.name not in ALLOWLISTED_ROOT_FILES:
            stray_files.add(rs_file)

    # Also check immediate subdirectories that aren't crates
    for item in repo_root.iterdir():
        if item.is_dir() and not (item / "Cargo.toml").exists():
            if item.name not in SKIP_DIRS:
                for rs_file in item.glob("*.rs"):
                    if rs_file.name not in ALLOWLISTED_ROOT_FILES:
                        stray_files.add(rs_file)

    return stray_files


def main():
    repo_root = Path(__file__).parent.parent
    if not repo_root.exists():
        print(f"Error: Repository root not found at {repo_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Checking for orphaned modules in {repo_root}...")

    # Find all crates
    crates = find_crates(repo_root)
    print(f"Found {len(crates)} crates")

    total_orphans = 0
    has_errors = False

    for cargo_toml, crate_root in sorted(crates.items()):
        print(f"\nChecking crate: {cargo_toml.parent}")
        reachable, orphans = check_crate(crate_root)

        if orphans:
            has_errors = True
            print(f"  ERROR: {len(orphans)} orphaned module(s) found:")
            for orphan in sorted(orphans):
                rel_path = orphan.relative_to(repo_root)
                print(f"    - {rel_path}")
            total_orphans += len(orphans)
        else:
            print(f"  OK: All {len(reachable)} modules are reachable")

    # Check for stray files
    stray_files = check_stray_files(repo_root)
    if stray_files:
        has_errors = True
        print(f"\nERROR: {len(stray_files)} stray .rs file(s) found outside crate src/:")
        for stray in sorted(stray_files):
            rel_path = stray.relative_to(repo_root)
            print(f"  - {rel_path}")
    else:
        print("\nOK: No stray .rs files found outside crate src/")

    if has_errors:
        print(f"\nTotal issues: {total_orphans + len(stray_files)}")
        print("Please either wire in orphaned modules or remove unused files.")
        sys.exit(1)
    else:
        print("\nAll checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
