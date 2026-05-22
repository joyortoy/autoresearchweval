#!/usr/bin/env bash
set -euo pipefail

run_optional_evals() {
  local root_dir="$1"
  if [[ "${AUTORESEARCH_ENABLE_OPTIONAL_EVALS:-0}" != "1" ]]; then
    echo "Optional eval adapters disabled (AUTORESEARCH_ENABLE_OPTIONAL_EVALS!=1)."
    return 0
  fi
  if [[ "${AUTORESEARCH_INTENT_EVAL:-0}" == "1" || "${AUTORESEARCH_RETRIEVAL_EVAL:-0}" == "1" ]]; then
    echo "Optional eval adapters enabled via existing launcher logic."
  fi
}
