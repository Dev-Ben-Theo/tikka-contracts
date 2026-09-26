# Testing Guide

This guide explains how to run and extend Tikka’s unit, integration, and fuzz tests. Commands below work from a fresh clone after installing the prerequisites for each layer.

## Prerequisites

| Layer | Requirements |
|-------|----------------|
| Contract unit / integration | Stable Rust, `wasm32-unknown-unknown` target (`rustup target add wasm32-unknown-unknown`) |
| Oracle Jest suite | Node.js 20+, packages in `oracle/` (`cd oracle && npm ci`) |
| Fuzz targets | Nightly Rust, `cargo-fuzz`, Linux or WSL (`rustup toolchain install nightly && cargo install cargo-fuzz`) |

Setup troubleshooting (WASM target, Stellar CLI skew, Node version) is covered in [`FAQ.md`](FAQ.md).

## Quick reference

```bash
# Contract crates (from repo root)
cargo test -p raffle-shared
cargo test -p raffle-factory
cargo test -p raffle-instance
cargo test --workspace

# Oracle (from oracle/)
cd oracle
npm ci
npm test

# Fuzz (Linux/WSL, nightly; from repo root)
cargo +nightly fuzz run fuzz_buy_ticket -- -max_total_time=60
cargo +nightly fuzz run fuzz_finalize_raffle -- -max_total_time=60
cargo +nightly fuzz run fuzz_winner_selection -- -max_total_time=60

# Cross-platform fuzz smoke tests (stable Rust, any OS)
cargo test -p raffle-fuzz
```

CI runs `cargo test --workspace` and `npm test` in `oracle/` on every pull request (see `.github/workflows/ci.yml`).

---

## Unit and integration tests (Rust / Soroban)

### What lives where

| Crate | Role | Where tests live |
|-------|------|------------------|
| `raffle-shared` | Shared types and pure helpers (e.g. `effective_limit`) | `#[cfg(test)]` modules in `contracts/raffle-shared/src/lib.rs` |
| `raffle-factory` | Factory contract | Tests co-located in `contracts/raffle-factory/src/lib.rs` / related modules |
| `raffle-instance` | Per-raffle instance contract | `contracts/raffle-instance/src/test.rs` |

Contract tests use the Soroban SDK test environment (`Env::default()`, `env.mock_all_auths()`, `testutils`). They are integration-style: they register contracts, mint test tokens, and exercise public entrypoints.

### Commands

From the repository root:

```bash
cargo test -p raffle-shared
cargo test -p raffle-factory
cargo test -p raffle-instance

# Optional: filter by test name
cargo test -p raffle-instance test_oracle_fallback

# Full workspace (matches CI)
cargo test --workspace
```

Before opening a PR, also run formatting and Clippy as CI does:

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
```

### Naming and helper conventions (`test.rs`)

Follow the house style used in `contracts/raffle-instance/src/test.rs`:

1. **Module header** — start with `#![cfg(test)]`, `use super::*;`, and Soroban `testutils` imports.
2. **Test names** — prefer descriptive `snake_case` names that state the behavior under test (`test_oracle_fallback_with_ledger_delays`, `non_winner_cannot_claim`). Prefix with `test_` when it aids grepping; issue numbers in comments (`// #449`) are welcome for context.
3. **Env bootstrap** — every test typically starts with:
   ```rust
   let env = Env::default();
   env.mock_all_auths();
   ```
   Advance time or sequence with `env.ledger().with_mut(|l| { ... })` when testing deadlines or timeouts.
4. **Shared setup helpers** — extract repeated scaffolding instead of duplicating it:
   - `setup_active_raffle(...)` — funded raffle ready for ticket sales
   - `setup_external_drawing_raffle(...)` — external-oracle drawing path
   - `lifecycle_config(...)` — builds a `RaffleConfig` with sensible defaults
   - Small assert helpers such as `assert_drawing_lock_cleared(...)`
5. **Config builders** — construct `RaffleConfig { ... }` explicitly for the scenario; use named constants from `raffle_shared` (e.g. `DEFAULT_CLAIM_LOCKUP_SECONDS`) in assertions rather than magic numbers when those constants define the expected behavior.
6. **Token setup** — register a stellar asset with `env.register_stellar_asset_contract_v2(...)`, then mint via `StellarAssetClient`.
7. **Clients** — register with `env.register(RaffleInstance, ())` and call through `RaffleInstanceClient`. Prefer `try_*` methods when asserting specific `Error` variants.

When adding tests to other crates, mirror the same patterns: focused helpers, clear names, and assertions against shared constants where applicable.

---

## Oracle tests (TypeScript / Jest)

The off-chain oracle under `oracle/` has a Jest suite (`*.test.ts` next to sources).

```bash
cd oracle
npm ci          # clean install from package-lock.json
npm run build   # TypeScript compile check
npm test        # jest --passWithNoTests
```

Write new tests as `*.test.ts` beside the module under test. Prefer small, deterministic unit tests for services (keys, VRF, submitter, listener). Integration-style checks that need live RPC or secrets should stay behind env vars documented in `oracle/README.md` and should not break the default `npm test` run.

---

## Fuzz tests (`cargo-fuzz`)

Fuzz targets live in `fuzz/fuzz_targets/` and exercise pure numeric / state-machine guards extracted from contract logic (no Soroban host). Details and corpus/crash reproduction are also documented in [`fuzz/README.md`](../fuzz/README.md).

| Target | Focus |
|--------|--------|
| `fuzz_buy_ticket` | Sold-out cap, deadline, multi-ticket policy, sold counter |
| `fuzz_finalize_raffle` | Winner-index bounds for internal and external randomness paths |
| `fuzz_winner_selection` | Winner selection invariants |

### Running with nightly

`cargo-fuzz` requires nightly and typically Linux or WSL:

```bash
rustup toolchain install nightly
cargo install cargo-fuzz

# From repo root — short smoke run
cargo +nightly fuzz run fuzz_buy_ticket -- -max_total_time=60

# Longer soak (e.g. 30 minutes)
cargo +nightly fuzz run fuzz_finalize_raffle -- -max_total_time=1800
cargo +nightly fuzz run fuzz_winner_selection -- -max_total_time=1800
```

### Smoke tests on any platform

Each fuzz target embeds deterministic smoke tests runnable on stable Rust:

```bash
cargo test -p raffle-fuzz
```

### Crashes and corpus

- Crashes land in `fuzz/artifacts/<target-name>/crash-<hash>` — reproduce with  
  `cargo +nightly fuzz run <target-name> fuzz/artifacts/<target-name>/crash-<hash>`
- Interesting inputs accumulate in `fuzz/corpus/<target-name>/` — commit corpus updates that lock in regressions you care about.

---

## When to add a unit test vs a fuzz target

| Prefer… | When… |
|---------|--------|
| **Unit / integration test** | You know the inputs and expected outcomes (happy path, specific error code, boundary values like `effective_limit(0)` / `u32::MAX`). Regression for a fixed bug. API contract changes. |
| **Fuzz target** | Invariants must hold for *arbitrary* inputs (index always in bounds, counters never overflow policy, sold-out never oversells). Large combinatorial state spaces where hand-written cases miss edge combinations. |

Practical rule of thumb:

1. Fix or feature first gets a focused `#[test]` (or Jest case) with named constants and clear asserts.
2. If the logic is a closed numeric/state machine with many interacting fields, add or extend a fuzz harness that asserts invariants, plus a few smoke cases in the same file so `cargo test -p raffle-fuzz` stays green on Windows/macOS CI contributors.

Do **not** replace unit tests with fuzz-only coverage: CI always runs `cargo test --workspace`; long fuzz soaks are optional local/CI jobs.

---

## Coverage ratchet

Rust line coverage is enforced by a ratchet: `scripts/check_coverage_ratchet.py`
compares the current `lcov` output against the committed floor in
`coverage/coverage-ratchet.json`. Coverage must never decrease — per file or
overall — and a missing baseline entry fails loudly instead of passing
silently. Deleting a test file without re-baselining fails the check.

```bash
# Collect coverage (pinned toolchain, from repo root)
cargo llvm-cov --workspace --lcov --output-path coverage/lcov.info

# Check against the committed floor (this is what CI runs)
python3 scripts/check_coverage_ratchet.py \
  --lcov coverage/lcov.info \
  --baseline coverage/coverage-ratchet.json
```

### Raising the floor

Coverage increases are adopted explicitly: re-run with `--update-baseline`
and commit the regenerated JSON **in the same PR** so the new floor is a
reviewable diff.

```bash
python3 scripts/check_coverage_ratchet.py \
  --lcov coverage/lcov.info \
  --baseline coverage/coverage-ratchet.json \
  --update-baseline
git diff coverage/coverage-ratchet.json  # review, then commit
```

Rules of thumb:

- New behavior should keep or raise coverage; a drop means either missing
  tests or dead code to remove.
- If you intentionally delete a covered file, re-baseline in the same PR and
  call it out in the PR description.
- Never hand-edit the baseline numbers — always regenerate from a clean
  `cargo llvm-cov` run on the pinned toolchain.

---

## Checklist before opening a PR

- [ ] `cargo test -p <crate>` (or `--workspace`) passes for crates you touched
- [ ] `cargo fmt --all` applied; Clippy clean if you changed Rust
- [ ] If you changed `oracle/`, `cd oracle && npm test` (and format checks if configured) passes
- [ ] New behavior has a unit/integration test, or a documented fuzz invariant when appropriate
- [ ] Docs updated when test commands or conventions change
