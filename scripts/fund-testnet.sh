#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PUBLIC_KEY="${1:-}"

if [[ -z "${PUBLIC_KEY}" ]]; then
    echo "Usage: ./scripts/fund-testnet.sh <stellar_public_key>" >&2
    exit 1
fi

echo "Funding account ${PUBLIC_KEY} on Testnet..."
curl -s --get --data-urlencode "addr=${PUBLIC_KEY}" "https://friendbot.stellar.org/"

echo ""
echo "Funding complete!"
