#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${AUTORESEARCH_LOG_DIR:-${ROOT_DIR}/logs}"
SWEEP_TS="$(date +%Y%m%d_%H%M%S)"
SUMMARY_CSV="${LOG_DIR}/sweep_${SWEEP_TS}.csv"
MODE="${1:-full}"

mkdir -p "${LOG_DIR}"
echo "run_name,mode,device_batch_size,depth,status,val_bpb,train_log" > "${SUMMARY_CSV}"

run_config() {
  local device_batch_size="$1"
  local depth="$2"
  local run_name="bs${device_batch_size}_d${depth}_${SWEEP_TS}"
  local train_log="${LOG_DIR}/${run_name}_train.log"
  local status="ok"
  local val_bpb=""
  local total_batch_size=524288

  echo "=== sweep run: batch=${device_batch_size} depth=${depth} mode=${MODE} ==="
  if (( total_batch_size % (device_batch_size * 2048) != 0 )); then
    total_batch_size=491520
  fi
  if AUTORESEARCH_RUN_NAME="${run_name}" \
     AUTORESEARCH_DEVICE_BATCH_SIZE="${device_batch_size}" \
     AUTORESEARCH_DEPTH="${depth}" \
     AUTORESEARCH_TOTAL_BATCH_SIZE="${total_batch_size}" \
     "${ROOT_DIR}/run_intent_autoresearch.sh" "${MODE}"; then
    :
  else
    status="failed"
  fi

  if [[ -f "${train_log}" ]]; then
    val_bpb="$(awk '/^val_bpb:/ {print $2}' "${train_log}" | tail -n 1)"
    if [[ -z "${val_bpb}" && "${status}" == "ok" ]]; then
      status="incomplete"
    fi
  else
    train_log=""
    if [[ "${MODE}" == "full" ]]; then
      status="missing-log"
    fi
  fi

  echo "${run_name},${MODE},${device_batch_size},${depth},${status},${val_bpb},${train_log}" >> "${SUMMARY_CSV}"
}

for cfg in \
  "20 8" \
  "24 8" \
  "16 6" \
  "24 6"
do
  run_config ${cfg}
done

echo "Sweep summary: ${SUMMARY_CSV}"
if command -v column >/dev/null 2>&1; then
  column -s, -t "${SUMMARY_CSV}"
else
  cat "${SUMMARY_CSV}"
fi
