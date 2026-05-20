#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${AUTORESEARCH_LOG_DIR:-${ROOT_DIR}/logs}"
SUPERVISOR_LOG="${LOG_DIR}/autoresearch_supervisor.log"
LOCK_FILE="${ROOT_DIR}/.autoresearch_forever.lock"
SLEEP_BETWEEN_RUNS_SEC="${AUTORESEARCH_SLEEP_BETWEEN_RUNS_SEC:-15}"
OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE="${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE:-0}"

mkdir -p "${LOG_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Another autoresearch forever loop is already running." | tee -a "${SUPERVISOR_LOG}"
  exit 1
fi

echo "[$(date --iso-8601=seconds)] autoresearch forever loop starting" | tee -a "${SUPERVISOR_LOG}"
echo "[$(date --iso-8601=seconds)] OpenClaw memory bridge enabled: ${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE}" | tee -a "${SUPERVISOR_LOG}"

while true; do
  echo "[$(date --iso-8601=seconds)] starting full run" | tee -a "${SUPERVISOR_LOG}"
  if OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE="${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE}" \
    "${ROOT_DIR}/run_intent_autoresearch.sh" full >>"${SUPERVISOR_LOG}" 2>&1; then
    echo "[$(date --iso-8601=seconds)] run completed successfully" | tee -a "${SUPERVISOR_LOG}"
  else
    status=$?
    echo "[$(date --iso-8601=seconds)] run failed with exit code ${status}" | tee -a "${SUPERVISOR_LOG}"
  fi

  echo "[$(date --iso-8601=seconds)] sleeping ${SLEEP_BETWEEN_RUNS_SEC}s before next run" | tee -a "${SUPERVISOR_LOG}"
  sleep "${SLEEP_BETWEEN_RUNS_SEC}"
done
