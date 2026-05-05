#!/bin/sh
# One-time setup for coograph.
# Run this after cloning so git pull auto-syncs to registered projects.

set -e

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$REPO_ROOT"

# Point git hooks to the checked-in hooks directory
git config --local core.hooksPath .github/hooks
echo "Git hooks configured (core.hooksPath = .github/hooks)"

# Ensure uv is available (needed for code-graph MCP server)
if ! command -v uv >/dev/null 2>&1; then
    echo "WARNING: 'uv' not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
else
    echo "uv found: $(uv --version)"
fi

echo "Done. Future 'git pull' will auto-sync to registered projects."
