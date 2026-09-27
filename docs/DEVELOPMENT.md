# Development Guide

This guide covers the repository workflow. The current checkout is part of a
build-repair and hardening pass, so commands and feature descriptions below do
not imply that the workspace currently compiles.

## Prerequisites

- Rust and `rustup`
- The `wasm32-unknown-unknown` Rust target
- Stellar CLI compatible with the deployment scripts
- Node.js 20 or newer for `oracle/`

Install the WebAssembly target with:

```bash
rustup target add wasm32-unknown-unknown
```

## Local Checks

Run focused checks before opening a pull request. The workspace currently has
known build issues, so record any failure and consult the relevant issue before
claiming a green build.

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features
cargo test
cargo build --target wasm32-unknown-unknown --release
```

For the oracle service:

```bash
cd oracle
npm install
npm run lint
npm test -- --runInBand
```

See [TESTING.md](TESTING.md) for the test layout and [FAQ.md](FAQ.md) for
common environment and toolchain problems. Do not treat stale implementation
plans or status notes as evidence that a feature works.

## Build Targets

The two contract packages are `raffle-factory` and `raffle-instance`:

```bash
cargo build --target wasm32-unknown-unknown --release -p raffle-factory
cargo build --target wasm32-unknown-unknown --release -p raffle-instance
```

Deployment and verification instructions are maintained in
[DEPLOYMENT.md](DEPLOYMENT.md). Storage tiers and TTL policy are maintained in
[STORAGE.md](STORAGE.md).

## Contribution Conventions

Use a descriptive branch prefix such as `feat/`, `fix/`, `docs/`, `test/`, or
`chore/`. Keep pull requests focused, document externally visible changes, and
update the relevant document in this directory rather than adding a temporary
root-level status or plan file.

See the root [CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution and
review process.
