#!/usr/bin/env bash
set -euo pipefail
# Compatibility wrapper: Python-first orchestrator.
exec uv run python -m autoresearch.orchestrator "$@"
