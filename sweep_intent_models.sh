#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${AUTORESEARCH_LOG_DIR:-${ROOT_DIR}/logs}"
SWEEP_TS="$(date +%Y%m%d_%H%M%S)"
SUMMARY_CSV="${LOG_DIR}/intent_sweep_${SWEEP_TS}.csv"
INTENTSTACK_URL="${OPENCLAW_INTENTSTACK_URL:-http://127.0.0.1:8090}"

mkdir -p "${LOG_DIR}"
echo "run_name,intent_model,memory_model,status,health_status,active_intent_model,active_memory_model,reply_log" > "${SUMMARY_CSV}"

run_pair() {
  local intent_model="$1"
  local memory_model="$2"
  local run_name="intent_${SWEEP_TS}_$(echo "${intent_model}__${memory_model}" | tr ':/' '__')"
  local reply_log="${LOG_DIR}/${run_name}_intent.log"
  local status="ok"
  local health_status=""
  local active_intent_model=""
  local active_memory_model=""

  echo "=== intent sweep: ${intent_model} + ${memory_model} ==="
  if FORCE_RESTART_INTENTSTACK=1 \
     AUTORESEARCH_RUN_NAME="${run_name}" \
     INTENTSTACK_MODEL_INTENT="${intent_model}" \
     INTENTSTACK_MODEL_MEMORY_AGENT="${memory_model}" \
     "${ROOT_DIR}/run_intent_autoresearch.sh" smoke; then
    :
  else
    status="failed"
  fi

  read -r health_status active_intent_model active_memory_model < <(
    curl -fsS -m 4 "${INTENTSTACK_URL}/admin/health" | python3 -c 'import json,sys
data = json.load(sys.stdin)
models = data.get("models", {})
print(
    data.get("status", ""),
    models.get("intent", ""),
    models.get("memory_agent", ""),
)' 2>/dev/null || printf '  '
  )

  if [[ "${status}" == "ok" ]] && [[ "${active_intent_model}" != "${intent_model}" || "${active_memory_model}" != "${memory_model}" ]]; then
    status="mismatch"
  fi

  if [[ ! -f "${reply_log}" ]]; then
    reply_log=""
    if [[ "${status}" == "ok" ]]; then
      status="missing-log"
    fi
  fi

  echo "${run_name},${intent_model},${memory_model},${status},${health_status},${active_intent_model},${active_memory_model},${reply_log}" >> "${SUMMARY_CSV}"
}

for pair in \
  "glm4:9b qwen2.5:7b-instruct" \
  "glm4:9b qwen2.5-coder:32b-instruct" \
  "qwen2.5:7b-instruct qwen2.5:7b-instruct" \
  "qwen2.5-coder:32b-instruct qwen2.5:7b-instruct"
do
  run_pair ${pair}
done

echo "Intent sweep summary: ${SUMMARY_CSV}"
if command -v column >/dev/null 2>&1; then
  column -s, -t "${SUMMARY_CSV}"
else
  cat "${SUMMARY_CSV}"
fi
