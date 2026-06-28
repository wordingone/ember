#!/usr/bin/env bash
# Point this clone's git hooks at the committed .githooks directory.
# Run once after cloning. Idempotent.
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* tools/repo-guard.sh 2>/dev/null || true
echo "hooks installed: core.hooksPath -> .githooks"
echo "verify: git config core.hooksPath"
