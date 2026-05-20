#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTENTSTACK_DIR="${INTENTSTACK_DIR:-/home/sam/memory/intentstack}"
JOYORTOY_DIR="${JOYORTOY_DIR:-/home/sam/projects/Joyortoy}"
INTENTSTACK_URL="${OPENCLAW_INTENTSTACK_URL:-http://127.0.0.1:8090}"
INTENT_MODEL="${OPENCLAW_INTENT_MODEL:-glm4:9b}"
INTENTSTACK_MODEL_INTENT="${INTENTSTACK_MODEL_INTENT:-${INTENT_MODEL}}"
INTENTSTACK_MODEL_MEMORY_AGENT="${INTENTSTACK_MODEL_MEMORY_AGENT:-qwen2.5:7b-instruct}"
FORCE_RESTART_INTENTSTACK="${FORCE_RESTART_INTENTSTACK:-0}"
CONV_ID="${OPENCLAW_CONV_ID:-openclaw-smoke-$(date +%s)}"
RUN_MODE="${1:-full}"
OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE="${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE:-0}"
AUTORESEARCH_INTENT_SMOKE_MIN_FREE_MB="${AUTORESEARCH_INTENT_SMOKE_MIN_FREE_MB:-12000}"
LOG_DIR="${AUTORESEARCH_LOG_DIR:-${ROOT_DIR}/logs}"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
RUN_NAME="${AUTORESEARCH_RUN_NAME:-autoresearch_${RUN_TS}}"
INTENT_LOG="${LOG_DIR}/${RUN_NAME}_intent.log"
TRAIN_LOG="${LOG_DIR}/${RUN_NAME}_train.log"
JUDGE_LOG="${LOG_DIR}/${RUN_NAME}_judge.json"
QMD_SRC_DIR="${QMD_SRC_DIR:-/home/sam/qmd-src}"
AUTORESEARCH_RETRIEVAL_EVAL="${AUTORESEARCH_RETRIEVAL_EVAL:-1}"
AUTORESEARCH_RETRIEVAL_CORPUS="${AUTORESEARCH_RETRIEVAL_CORPUS:-/home/sam/memory/intentstack-memory-backfill}"
AUTORESEARCH_RETRIEVAL_CASES="${AUTORESEARCH_RETRIEVAL_CASES:-${LOG_DIR}/${RUN_NAME}_retrieval_cases.json}"
AUTORESEARCH_RETRIEVAL_REPORT="${AUTORESEARCH_RETRIEVAL_REPORT:-${LOG_DIR}/${RUN_NAME}_retrieval_eval.json}"
AUTORESEARCH_RETRIEVAL_MODEL="${AUTORESEARCH_RETRIEVAL_MODEL:-ollama:qwen3-embedding:0.6b}"
AUTORESEARCH_INTENT_EVAL="${AUTORESEARCH_INTENT_EVAL:-1}"
AUTORESEARCH_INTENT_EVAL_BASE_FILE="${AUTORESEARCH_INTENT_EVAL_BASE_FILE:-${INTENTSTACK_DIR}/intent_eval_set.jsonl}"
AUTORESEARCH_INTENT_EVAL_CONFUSING_FILE="${AUTORESEARCH_INTENT_EVAL_CONFUSING_FILE:-${INTENTSTACK_DIR}/intent_eval_confusing_set.jsonl}"
AUTORESEARCH_INTENT_EVAL_BASE_REPORT="${AUTORESEARCH_INTENT_EVAL_BASE_REPORT:-${LOG_DIR}/${RUN_NAME}_intent_eval_base.json}"
AUTORESEARCH_INTENT_EVAL_CONFUSING_REPORT="${AUTORESEARCH_INTENT_EVAL_CONFUSING_REPORT:-${LOG_DIR}/${RUN_NAME}_intent_eval_confusing.json}"
RESULTS_TSV="${AUTORESEARCH_RESULTS_TSV:-${ROOT_DIR}/results.tsv}"
BEST_CONFIG_JSON="${AUTORESEARCH_BEST_CONFIG_JSON:-${ROOT_DIR}/best_config.json}"
EXPERIMENT_JSON="${AUTORESEARCH_EXPERIMENT_JSON:-${ROOT_DIR}/.last_experiment.json}"
AUTORESEARCH_DISCORD_WEBHOOK_URL="${AUTORESEARCH_DISCORD_WEBHOOK_URL:-}"
AUTORESEARCH_DISCORD_USERNAME="${AUTORESEARCH_DISCORD_USERNAME:-autoresearch}"
AUTORESEARCH_DISCORD_AVATAR_URL="${AUTORESEARCH_DISCORD_AVATAR_URL:-}"

mkdir -p "${LOG_DIR}"

case "${RUN_MODE}" in
  smoke|full)
    ;;
  *)
    echo "Usage: $0 [smoke|full]" >&2
    exit 1
    ;;
esac

ensure_results_header() {
  if [[ ! -f "${RESULTS_TSV}" ]]; then
    printf 'commit\tval_bpb\tmemory_gb\tstatus\tdescription\n' > "${RESULTS_TSV}"
  fi
}

discord_notify() {
  local title="$1"
  local body="${2:-}"
  if [[ -z "${AUTORESEARCH_DISCORD_WEBHOOK_URL}" ]]; then
    return 0
  fi
  AUTORESEARCH_DISCORD_WEBHOOK_URL="${AUTORESEARCH_DISCORD_WEBHOOK_URL}" \
  AUTORESEARCH_DISCORD_USERNAME="${AUTORESEARCH_DISCORD_USERNAME}" \
  AUTORESEARCH_DISCORD_AVATAR_URL="${AUTORESEARCH_DISCORD_AVATAR_URL}" \
  RUN_NAME="${RUN_NAME}" \
  RUN_MODE="${RUN_MODE}" \
  INTENTSTACK_MODEL_INTENT="${INTENTSTACK_MODEL_INTENT}" \
  INTENTSTACK_MODEL_MEMORY_AGENT="${INTENTSTACK_MODEL_MEMORY_AGENT}" \
  CLAWVAULT_QMD_COLLECTION="${CLAWVAULT_QMD_COLLECTION:-}" \
  LOG_DIR="${LOG_DIR}" \
  TITLE="${title}" \
  BODY="${body}" \
  python3 - <<'PY' >/dev/null 2>&1 || true
import json
import os
import urllib.request

url = os.environ.get("AUTORESEARCH_DISCORD_WEBHOOK_URL", "").strip()
if not url:
    raise SystemExit(0)

title = os.environ.get("TITLE", "").strip()
body = os.environ.get("BODY", "").strip()
run_name = os.environ.get("RUN_NAME", "").strip()
run_mode = os.environ.get("RUN_MODE", "").strip()
intent_model = os.environ.get("INTENTSTACK_MODEL_INTENT", "").strip()
memory_model = os.environ.get("INTENTSTACK_MODEL_MEMORY_AGENT", "").strip()
collection = os.environ.get("CLAWVAULT_QMD_COLLECTION", "").strip() or "(default)"
log_dir = os.environ.get("LOG_DIR", "").strip()

lines = [
    f"run: `{run_name}`",
    f"mode: `{run_mode}`",
    f"intent: `{intent_model}`",
    f"memory_agent: `{memory_model}`",
    f"collection: `{collection}`",
]
if log_dir:
    lines.append(f"log_dir: `{log_dir}`")
if body:
    lines.append(body)

payload = {
    "username": os.environ.get("AUTORESEARCH_DISCORD_USERNAME", "autoresearch"),
    "content": f"**{title}**\n" + "\n".join(lines),
}
avatar = os.environ.get("AUTORESEARCH_DISCORD_AVATAR_URL", "").strip()
if avatar:
    payload["avatar_url"] = avatar

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as resp:
    resp.read()
PY
}

run_retrieval_eval() {
  if [[ "${AUTORESEARCH_RETRIEVAL_EVAL}" != "1" ]]; then
    return 0
  fi

  if [[ ! -d "${QMD_SRC_DIR}" ]]; then
    echo "Skipping retrieval eval: QMD_SRC_DIR not found at ${QMD_SRC_DIR}" >&2
    return 0
  fi

  local collection="${CLAWVAULT_QMD_COLLECTION:-intent-memory}"
  echo "Building retrieval cases from ${AUTORESEARCH_RETRIEVAL_CORPUS}"
  python3 "${QMD_SRC_DIR}/scripts/build_intent_memory_cases.py" \
    --corpus "${AUTORESEARCH_RETRIEVAL_CORPUS}" \
    --collection "${collection}" \
    --output "${AUTORESEARCH_RETRIEVAL_CASES}"

  echo "Running retrieval eval against collection ${collection}"
  python3 "${QMD_SRC_DIR}/scripts/eval_retrieval_ab.py" \
    --cases "${AUTORESEARCH_RETRIEVAL_CASES}" \
    --collection "${collection}" \
    --mode query \
    --model "live=${AUTORESEARCH_RETRIEVAL_MODEL}" \
    --config "baseline" \
    --config "wide-candidates:QMD_RERANK_CANDIDATE_LIMIT=60" \
    --final-model "${AUTORESEARCH_RETRIEVAL_MODEL}" \
    --output "${AUTORESEARCH_RETRIEVAL_REPORT}"

  local summary best_label best_limit
  summary="$(python3 - "${AUTORESEARCH_RETRIEVAL_REPORT}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
runs = data.get("runs", [])
best = None
for run in runs:
    mode = run.get("modes", {}).get("query", {})
    summary = mode.get("summary", {})
    hit1_num, _, hit1_den = str(summary.get("hit_at_1", "0/1")).partition("/")
    hitk_num, _, hitk_den = str(summary.get("hit_at_k", "0/1")).partition("/")
    row = (
        float(summary.get("mrr", 0.0)),
        int(hit1_num or 0),
        int(hitk_num or 0),
        -int(hit1_den or hitk_den or 1),
    )
    if best is None or row > best[0]:
        best = (
            row,
            run.get("config_label", "baseline"),
            run.get("env_overrides", {}).get("QMD_RERANK_CANDIDATE_LIMIT", ""),
            summary.get("hit_at_1", ""),
            summary.get("hit_at_k", ""),
            summary.get("mrr", 0.0),
        )
if best is None:
    print("none|||")
else:
    _, label, limit, hit1, hitk, mrr = best
    print(f"{label}|{limit}|{hit1}|{hitk}|{mrr}")
PY
)"
  IFS='|' read -r best_label best_limit best_hit1 best_hitk best_mrr <<< "${summary}"
  if [[ -n "${best_limit}" ]]; then
    export QMD_RERANK_CANDIDATE_LIMIT="${best_limit}"
    export CLAWVAULT_QMD_RERANK_CANDIDATE_LIMIT="${best_limit}"
  fi
  echo "Retrieval eval best config: ${best_label} (hit@1=${best_hit1} hit@5=${best_hitk} mrr=${best_mrr})"
  discord_notify "autoresearch retrieval eval" "config: \`${best_label}\`\nhit_at_1: \`${best_hit1}\`\nhit_at_5: \`${best_hitk}\`\nmrr: \`${best_mrr}\`\nreport: \`${AUTORESEARCH_RETRIEVAL_REPORT}\`"
}

run_single_intent_eval() {
  local label="$1"
  local eval_file="$2"
  local report_path="$3"

  if [[ ! -f "${eval_file}" ]]; then
    echo "Skipping ${label} intent eval: eval file not found at ${eval_file}" >&2
    return 0
  fi

  echo "Running ${label} intent eval from ${eval_file}"
  python3 "${INTENTSTACK_DIR}/eval_intent_ready.py" \
    --eval-file "${eval_file}" \
    --base-url "${INTENTSTACK_URL}" \
    --out-dir "${LOG_DIR}" >/tmp/autoresearch_intent_eval_${label}.log

  python3 - "${LOG_DIR}" "${report_path}" <<'PY'
import pathlib
import shutil
import sys

log_dir = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
reports = sorted(log_dir.glob("intent_eval_*.json"), key=lambda p: p.stat().st_mtime)
if not reports:
    raise SystemExit("No intent eval report produced")
src = reports[-1]
if src.resolve() != dest.resolve():
    shutil.copy2(src, dest)
print(dest)
PY
}

run_intent_evals() {
  if [[ "${AUTORESEARCH_INTENT_EVAL}" != "1" ]]; then
    return 0
  fi

  local summary base_summary confusing_summary

  run_single_intent_eval "base" "${AUTORESEARCH_INTENT_EVAL_BASE_FILE}" "${AUTORESEARCH_INTENT_EVAL_BASE_REPORT}"
  base_summary="$(python3 - "${AUTORESEARCH_INTENT_EVAL_BASE_REPORT}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
wrong = [row for row in data.get("results", []) if not row.get("correct")]
wrong_bits = [
    f"#{row.get('index')} {row.get('expected_intent')}->{row.get('predicted_intent') or '<none>'}"
    for row in wrong[:3]
]
print(
    f"accuracy: `{data.get('accuracy')}`\n"
    f"correct: `{data.get('correct')}/{data.get('total')}`\n"
    f"wrong: `{' ; '.join(wrong_bits) if wrong_bits else 'none'}`\n"
    f"report: `{sys.argv[1]}`"
)
PY
)"
  discord_notify "autoresearch intent eval base" "${base_summary}"

  run_single_intent_eval "confusing" "${AUTORESEARCH_INTENT_EVAL_CONFUSING_FILE}" "${AUTORESEARCH_INTENT_EVAL_CONFUSING_REPORT}"
  confusing_summary="$(python3 - "${AUTORESEARCH_INTENT_EVAL_CONFUSING_REPORT}" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
wrong = [row for row in data.get("results", []) if not row.get("correct")]
wrong_bits = [
    f"#{row.get('index')} {row.get('expected_intent')}->{row.get('predicted_intent') or '<none>'}"
    for row in wrong[:3]
]
print(
    f"accuracy: `{data.get('accuracy')}`\n"
    f"correct: `{data.get('correct')}/{data.get('total')}`\n"
    f"wrong: `{' ; '.join(wrong_bits) if wrong_bits else 'none'}`\n"
    f"report: `{sys.argv[1]}`"
)
PY
)"
  discord_notify "autoresearch intent eval confusing" "${confusing_summary}"
}

ensure_best_config() {
  if [[ -f "${BEST_CONFIG_JSON}" ]]; then
    return
  fi
  python3 - <<'PY' > "${BEST_CONFIG_JSON}"
import json
import os

cfg = {
    "device_batch_size": int(os.getenv("AUTORESEARCH_DEVICE_BATCH_SIZE", "16")),
    "total_batch_size": int(os.getenv("AUTORESEARCH_TOTAL_BATCH_SIZE", str(2**19))),
    "depth": int(os.getenv("AUTORESEARCH_DEPTH", "8")),
    "aspect_ratio": int(os.getenv("AUTORESEARCH_ASPECT_RATIO", "64")),
    "head_dim": int(os.getenv("AUTORESEARCH_HEAD_DIM", "128")),
    "window_pattern": os.getenv("AUTORESEARCH_WINDOW_PATTERN", "SSSL"),
    "embedding_lr": float(os.getenv("AUTORESEARCH_EMBEDDING_LR", "0.6")),
    "unembedding_lr": float(os.getenv("AUTORESEARCH_UNEMBEDDING_LR", "0.004")),
    "matrix_lr": float(os.getenv("AUTORESEARCH_MATRIX_LR", "0.04")),
    "scalar_lr": float(os.getenv("AUTORESEARCH_SCALAR_LR", "0.5")),
    "weight_decay": float(os.getenv("AUTORESEARCH_WEIGHT_DECAY", "0.2")),
    "warmup_ratio": float(os.getenv("AUTORESEARCH_WARMUP_RATIO", "0.0")),
    "warmdown_ratio": float(os.getenv("AUTORESEARCH_WARMDOWN_RATIO", "0.5")),
    "final_lr_frac": float(os.getenv("AUTORESEARCH_FINAL_LR_FRAC", "0.0")),
    "description": "baseline",
}
print(json.dumps(cfg, indent=2, ensure_ascii=False))
PY
}

choose_experiment() {
  python3 - "${BEST_CONFIG_JSON}" "${RESULTS_TSV}" <<'PY' > "${EXPERIMENT_JSON}"
import csv
import json
import sys
from pathlib import Path

best_path = Path(sys.argv[1])
results_path = Path(sys.argv[2])
best = json.loads(best_path.read_text())

rows = []
if results_path.exists():
    with results_path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)

run_idx = len(rows)
last_row = rows[-1] if rows else {}
last_status = (last_row.get("status") or "").strip()
last_desc = (last_row.get("description") or "").strip()

def clone(desc, **updates):
    cfg = dict(best)
    cfg.update(updates)
    cfg["description"] = desc
    return cfg

def safe_total_for(batch_size, accum_steps):
    return batch_size * 2048 * accum_steps


def smaller_batch_variants():
    current_bs = int(best["device_batch_size"])
    current_total = int(best["total_batch_size"])
    variants = []
    for bs, accum, desc in [
        (max(8, current_bs // 2), 16, "oom-backoff-batch-half"),
        (max(8, current_bs - 4), 16, "oom-backoff-batch-minus4"),
        (8, 16, "oom-backoff-batch-8"),
        (8, 8, "oom-backoff-total-quarter"),
    ]:
        total = min(current_total, safe_total_for(bs, accum))
        variants.append(clone(desc, device_batch_size=bs, total_batch_size=total))
    return variants


def oom_caused_by_shape(desc: str) -> bool:
    return any(token in desc for token in ("depth-", "wide", "compact-head"))

candidates = [
    clone("baseline-repeat"),
    clone("depth-6", depth=6, aspect_ratio=64),
    clone("depth-8-wide", depth=8, aspect_ratio=72),
    clone("depth-10-compact-head", depth=10, aspect_ratio=48, head_dim=96),
    clone("larger-device-batch", device_batch_size=24, total_batch_size=24 * 2048 * 16),
    clone("smaller-device-batch", device_batch_size=12, total_batch_size=12 * 2048 * 32),
    clone("window-ssll", window_pattern="SSLL"),
    clone("window-lssl", window_pattern="LSSL"),
    clone("higher-matrix-lr", matrix_lr=round(float(best["matrix_lr"]) * 1.15, 6)),
    clone("lower-matrix-lr", matrix_lr=round(float(best["matrix_lr"]) * 0.85, 6)),
    clone("higher-weight-decay", weight_decay=round(float(best["weight_decay"]) * 1.15, 6)),
    clone("lower-weight-decay", weight_decay=round(float(best["weight_decay"]) * 0.85, 6)),
    clone("warmup-5pct", warmup_ratio=0.05, warmdown_ratio=0.45),
    clone("final-lr-10pct", final_lr_frac=0.10),
]

if last_status == "crash":
    crash_desc = last_desc
    if oom_caused_by_shape(crash_desc):
        fallback = smaller_batch_variants() + [
            clone("oom-backoff-depth-6-batch-8", depth=6, device_batch_size=8, total_batch_size=safe_total_for(8, 16)),
            clone("oom-backoff-window-ssll", window_pattern="SSLL", device_batch_size=8, total_batch_size=safe_total_for(8, 16)),
        ]
    else:
        fallback = smaller_batch_variants()
    choice = fallback[run_idx % len(fallback)]
else:
    choice = candidates[run_idx % len(candidates)]
print(json.dumps(choice, indent=2, ensure_ascii=False))
PY
}

read_config_field() {
  local field="$1"
  python3 - "${EXPERIMENT_JSON}" "${field}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
value = data[sys.argv[2]]
print(value)
PY
}

extract_metric() {
  local key="$1"
  local log_file="$2"
  python3 - "${key}" "${log_file}" <<'PY'
import re, sys
key = sys.argv[1]
text = open(sys.argv[2], encoding="utf-8").read()
match = re.search(rf"^{re.escape(key)}:\s+([0-9.]+)$", text, re.MULTILINE)
print(match.group(1) if match else "")
PY
}

best_val_bpb() {
  python3 - "${RESULTS_TSV}" <<'PY'
import csv, math, sys
best = math.inf
try:
    with open(sys.argv[1], newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row.get("status") != "keep":
                continue
            try:
                value = float(row["val_bpb"])
            except Exception:
                continue
            best = min(best, value)
except FileNotFoundError:
    pass
print("" if math.isinf(best) else f"{best:.6f}")
PY
}

append_result_row() {
  local commit_hash="$1"
  local val_bpb="$2"
  local memory_gb="$3"
  local status="$4"
  local description="$5"
  printf '%s\t%s\t%s\t%s\t%s\n' "${commit_hash}" "${val_bpb}" "${memory_gb}" "${status}" "${description}" >> "${RESULTS_TSV}"
}

update_best_config() {
  cp "${EXPERIMENT_JSON}" "${BEST_CONFIG_JSON}"
}

check_intentstack() {
  curl -fsS -m 4 "${INTENTSTACK_URL}/admin/health" >/dev/null
}

health_json() {
  curl -fsS -m 4 "${INTENTSTACK_URL}/admin/health"
}

models_match() {
  local health
  health="$(health_json)"
  INTENTSTACK_MODEL_INTENT="${INTENTSTACK_MODEL_INTENT}" \
  INTENTSTACK_MODEL_MEMORY_AGENT="${INTENTSTACK_MODEL_MEMORY_AGENT}" \
  python3 -c 'import json, os, sys
data = json.loads(sys.argv[1])
want_intent = os.environ["INTENTSTACK_MODEL_INTENT"]
want_memory = os.environ["INTENTSTACK_MODEL_MEMORY_AGENT"]
models = data.get("models", {})
ok = models.get("intent") == want_intent and models.get("memory_agent") == want_memory and models.get("chat") == want_memory and models.get("judge") == want_memory
print("1" if ok else "0")' "${health}"
}

stop_intentstack() {
  local pids
  pids="$(pgrep -f '.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8090' || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping IntentStack pid(s): ${pids}"
    kill ${pids}
    local pid
    local waited=0
    while (( waited < 20 )); do
      local still_running=0
      for pid in ${pids}; do
        if kill -0 "${pid}" 2>/dev/null; then
          still_running=1
          break
        fi
      done
      if [[ "${still_running}" == "0" ]]; then
        break
      fi
      sleep 1
      waited=$((waited + 1))
    done
  fi
}

start_intentstack() {
  if check_intentstack; then
    if [[ "$(models_match)" == "1" ]]; then
      echo "IntentStack already healthy at ${INTENTSTACK_URL} with ${INTENTSTACK_MODEL_INTENT} + ${INTENTSTACK_MODEL_MEMORY_AGENT}"
      return
    fi
    if [[ "${FORCE_RESTART_INTENTSTACK}" != "1" ]]; then
      echo "IntentStack is healthy but model pair differs. Set FORCE_RESTART_INTENTSTACK=1 to restart with ${INTENTSTACK_MODEL_INTENT} + ${INTENTSTACK_MODEL_MEMORY_AGENT}"
      return
    fi
    stop_intentstack
  fi

  echo "Starting IntentStack from ${INTENTSTACK_DIR} with ${INTENTSTACK_MODEL_INTENT} + ${INTENTSTACK_MODEL_MEMORY_AGENT}"
  cd "${INTENTSTACK_DIR}"
  INTENTSTACK_MODEL_INTENT="${INTENTSTACK_MODEL_INTENT}" \
  INTENTSTACK_MODEL_MEMORY_AGENT="${INTENTSTACK_MODEL_MEMORY_AGENT}" \
  nohup .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8090 >/tmp/intentstack_uvicorn.log 2>&1 &
  local waited=0
  until check_intentstack; do
    sleep 1
    waited=$((waited + 1))
    if (( waited >= 20 )); then
      echo "IntentStack failed to become healthy within 20s" >&2
      tail -n 40 /tmp/intentstack_uvicorn.log >&2 || true
      return 1
    fi
  done
  echo "IntentStack is healthy at ${INTENTSTACK_URL}"
  health_json
}

run_intent_smoke() {
  echo "Running OpenClaw intent smoke test"
  echo "OpenClaw memory bridge enabled: ${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE}"
  check_smoke_gpu_headroom
  cd "${JOYORTOY_DIR}"
  PYTHONPATH=. \
  CLAWVAULT_PATH="${CLAWVAULT_PATH:-$HOME/memory}" \
  OPENCLAW_INTENTSTACK_URL="${INTENTSTACK_URL}" \
  OPENCLAW_INTENT_MODEL="${INTENTSTACK_MODEL_INTENT}" \
  OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE="${OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE}" \
  python3 -m openclaw.cognition.cli reply \
    --text "Give a 1-line health check acknowledgment" \
    --conv-id "${CONV_ID}" | tee "${INTENT_LOG}"
}

check_smoke_gpu_headroom() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "WARNING: nvidia-smi not found; skipping intent smoke GPU headroom check." >&2
    return 0
  fi

  local query
  set +e
  query="$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>&1)"
  local status=$?
  set -e
  if [[ "${status}" -ne 0 ]]; then
    echo "WARNING: nvidia-smi failed; skipping intent smoke GPU headroom check." >&2
    printf '%s\n' "${query}" >&2
    return 0
  fi

  local used_mb total_mb free_mb
  IFS=',' read -r used_mb total_mb <<< "${query}"
  used_mb="${used_mb//[[:space:]]/}"
  total_mb="${total_mb//[[:space:]]/}"
  free_mb=$((total_mb - used_mb))
  echo "GPU headroom before smoke: used=${used_mb}MB total=${total_mb}MB free=${free_mb}MB"
  if (( free_mb < AUTORESEARCH_INTENT_SMOKE_MIN_FREE_MB )); then
    echo "Intent smoke aborted: GPU free memory ${free_mb}MB is below required ${AUTORESEARCH_INTENT_SMOKE_MIN_FREE_MB}MB." >&2
    echo "Reduce concurrent GPU workloads or lower AUTORESEARCH_INTENT_SMOKE_MIN_FREE_MB to override." >&2
    return 1
  fi
}

run_judge_eval() {
  local description="$1"
  local val_bpb="$2"
  local memory_gb="$3"
  local metric_status="$4"
  local best_before="$5"
  local peak_vram_mb="$6"
  local judge_conv_id="${CONV_ID}-judge-${RUN_TS}"
  set +e
  local judge_output
  judge_output="$(INTENTSTACK_URL="${INTENTSTACK_URL}" \
  INTENTSTACK_MODEL_INTENT="${INTENTSTACK_MODEL_INTENT}" \
  ROOT_DIR="${ROOT_DIR}" \
  TRAIN_LOG="${TRAIN_LOG}" \
  JUDGE_LOG="${JUDGE_LOG}" \
  python3 - "$description" "$val_bpb" "$memory_gb" "$metric_status" "$best_before" "$peak_vram_mb" "$judge_conv_id" <<'PY' 2>&1
import json
import os
import sys
import urllib.request

description, val_bpb, memory_gb, metric_status, best_before, peak_vram_mb, conv_id = sys.argv[1:8]
train_log = os.environ["TRAIN_LOG"]
judge_log = os.environ["JUDGE_LOG"]
intentstack_url = os.environ["INTENTSTACK_URL"].rstrip("/")

tail = ""
try:
    with open(train_log, encoding="utf-8", errors="ignore") as handle:
        lines = handle.readlines()
    tail = "".join(lines[-25:])[-4000:]
except Exception as exc:
    tail = f"<train_log_unavailable: {exc}>"

prompt = f"""You are evaluating one autoresearch training run.
Return JSON only with this exact schema:
{{
  "verdict": "keep" | "discard",
  "confidence": 0.0,
  "summary": "short single-line reason",
  "risks": ["short item"],
  "checks": {{
    "metric_status_ok": true,
    "training_completed": true,
    "memory_within_bounds": true,
    "regression_risk": "low|medium|high"
  }}
}}

Rules:
- Prefer the measured metric over stylistic concerns.
- If metric_status is discard, verdict should normally be discard.
- Only return keep when the run looks completed, coherent, and not obviously risky.
- Keep summary under 160 chars.

Run facts:
- description: {description}
- metric_status: {metric_status}
- val_bpb: {val_bpb}
- best_before: {best_before}
- memory_gb: {memory_gb}
- peak_vram_mb: {peak_vram_mb}

Recent train log tail:
{tail}
"""

payload = {
    "model": os.environ.get("INTENTSTACK_MODEL_INTENT", "glm4:9b"),
    "messages": [{"role": "user", "content": prompt}],
    "stream": False,
    "user": conv_id,
    "agent_role": "system",
}

req = urllib.request.Request(
    f"{intentstack_url}/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=90) as resp:
    raw = resp.read().decode("utf-8")
outer = json.loads(raw)
content = outer["choices"][0]["message"]["content"]
start = content.find("{")
end = content.rfind("}")
if start == -1 or end == -1 or end < start:
    raise ValueError(f"Judge response did not contain JSON object: {content!r}")
judge = json.loads(content[start:end + 1])
with open(judge_log, "w", encoding="utf-8") as handle:
    json.dump(judge, handle, ensure_ascii=False, indent=2)
print(json.dumps(judge, ensure_ascii=False))
PY
)"
  local judge_status=$?
  set -e
  if [[ "${judge_status}" -ne 0 ]]; then
    echo "Judge evaluation unavailable; falling back to metric-only decision." >&2
    printf '%s\n' "${judge_output}" >&2
    return 1
  fi
  printf '%s\n' "${judge_output}" > "${JUDGE_LOG}"
  return 0
}

check_gpu_preflight() {
  echo "Running GPU preflight"
  local cuda_check
  set +e
  cuda_check="$(cd "${ROOT_DIR}" && uv run python - <<'PY' 2>&1
import torch
try:
    available = torch.cuda.is_available()
    count = torch.cuda.device_count()
    print(f"cuda_available={available}")
    print(f"device_count={count}")
    if available and count > 0:
        print(f"device_name={torch.cuda.get_device_name(0)}")
except Exception as exc:
    print(f"cuda_error={exc}")
    raise
PY
)"
  local cuda_status=$?
  set -e
  if [[ "${cuda_status}" -ne 0 ]]; then
    echo "GPU preflight failed: CUDA runtime is not usable." >&2
    printf '%s\n' "${cuda_check}" >&2
    echo "If a prior run wedged the driver, reboot or reset the NVIDIA driver before retrying." >&2
    return 1
  fi
  printf '%s\n' "${cuda_check}"

  local nvml_output
  set +e
  nvml_output="$(nvidia-smi 2>&1)"
  local nvml_status=$?
  set -e
  if [[ "${nvml_status}" -ne 0 ]]; then
    echo "WARNING: NVML is unhealthy even though CUDA is usable." >&2
    printf '%s\n' "${nvml_output}" >&2
    echo "Training may still work, but GPU telemetry and health reporting will be unreliable." >&2
  fi
}

run_autoresearch() {
  echo "Running autoresearch from ${ROOT_DIR}"
  cd "${ROOT_DIR}"
  check_gpu_preflight
  ensure_results_header
  ensure_best_config
  choose_experiment
  local description
  description="$(read_config_field description)"
  echo "Selected experiment: ${description}"
  discord_notify "autoresearch train started" "description: \`${description}\`"
  local train_status=0
  set +e
  env \
    AUTORESEARCH_DEVICE_BATCH_SIZE="$(read_config_field device_batch_size)" \
    AUTORESEARCH_TOTAL_BATCH_SIZE="$(read_config_field total_batch_size)" \
    AUTORESEARCH_DEPTH="$(read_config_field depth)" \
    AUTORESEARCH_ASPECT_RATIO="$(read_config_field aspect_ratio)" \
    AUTORESEARCH_HEAD_DIM="$(read_config_field head_dim)" \
    AUTORESEARCH_WINDOW_PATTERN="$(read_config_field window_pattern)" \
    AUTORESEARCH_EMBEDDING_LR="$(read_config_field embedding_lr)" \
    AUTORESEARCH_UNEMBEDDING_LR="$(read_config_field unembedding_lr)" \
    AUTORESEARCH_MATRIX_LR="$(read_config_field matrix_lr)" \
    AUTORESEARCH_SCALAR_LR="$(read_config_field scalar_lr)" \
    AUTORESEARCH_WEIGHT_DECAY="$(read_config_field weight_decay)" \
    AUTORESEARCH_WARMUP_RATIO="$(read_config_field warmup_ratio)" \
    AUTORESEARCH_WARMDOWN_RATIO="$(read_config_field warmdown_ratio)" \
    AUTORESEARCH_FINAL_LR_FRAC="$(read_config_field final_lr_frac)" \
    uv run train.py | tee "${TRAIN_LOG}"
  train_status=${PIPESTATUS[0]}
  set -e

  local val_bpb peak_vram_mb memory_gb best_so_far status commit_hash judge_verdict judge_summary
  val_bpb="$(extract_metric val_bpb "${TRAIN_LOG}")"
  peak_vram_mb="$(extract_metric peak_vram_mb "${TRAIN_LOG}")"
  commit_hash="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo nogit)"
  if [[ "${train_status}" -ne 0 || -z "${val_bpb}" || -z "${peak_vram_mb}" ]]; then
    append_result_row "${commit_hash}" "0.000000" "0.0" "crash" "${description}"
    echo "Experiment status: crash"
    discord_notify "autoresearch train crashed" "description: \`${description}\`\ntrain_log: \`${TRAIN_LOG}\`"
    return 1
  fi

  memory_gb="$(python3 - "${peak_vram_mb}" <<'PY'
import sys
print(f"{float(sys.argv[1]) / 1024.0:.1f}")
PY
)"
  best_so_far="$(best_val_bpb)"
  status="keep"
  if [[ -n "${best_so_far}" ]]; then
    status="$(python3 - "${val_bpb}" "${best_so_far}" <<'PY'
import sys
candidate = float(sys.argv[1])
best = float(sys.argv[2])
print("keep" if candidate < best else "discard")
PY
)"
  fi
  if run_judge_eval "${description}" "${val_bpb}" "${memory_gb}" "${status}" "${best_so_far:-none}" "${peak_vram_mb}"; then
    judge_verdict="$(python3 - "${JUDGE_LOG}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(data.get("verdict", ""))
PY
)"
    judge_summary="$(python3 - "${JUDGE_LOG}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(data.get("summary", ""))
PY
)"
    if [[ "${judge_verdict}" == "discard" && "${status}" == "keep" ]]; then
      status="discard"
    fi
    if [[ -n "${judge_verdict}" ]]; then
      echo "Judge verdict: ${judge_verdict}${judge_summary:+ - ${judge_summary}}"
    fi
  fi
  append_result_row "${commit_hash}" "${val_bpb}" "${memory_gb}" "${status}" "${description}"
  echo "Experiment status: ${status} (val_bpb=${val_bpb}, best_before=${best_so_far:-none})"
  discord_notify "autoresearch train finished" "description: \`${description}\`\nstatus: \`${status}\`\nval_bpb: \`${val_bpb}\`\npeak_vram_mb: \`${peak_vram_mb}\`\ntrain_log: \`${TRAIN_LOG}\`\njudge_log: \`${JUDGE_LOG}\`"
  if [[ "${status}" == "keep" ]]; then
    update_best_config
  fi
}

discord_notify "autoresearch run starting" "intent_log: \`${INTENT_LOG}\`"
start_intentstack
if run_intent_smoke; then
  discord_notify "autoresearch smoke passed" "intent_log: \`${INTENT_LOG}\`"
else
  discord_notify "autoresearch smoke failed" "intent_log: \`${INTENT_LOG}\`"
  exit 1
fi

run_intent_evals

run_retrieval_eval

if [[ "${RUN_MODE}" == "full" ]]; then
  run_autoresearch
else
  echo "Smoke mode complete"
  echo "Intent log: ${INTENT_LOG}"
  echo "Retrieval eval: ${AUTORESEARCH_RETRIEVAL_REPORT}"
fi

if [[ "${RUN_MODE}" == "full" ]]; then
  echo "Intent log: ${INTENT_LOG}"
  echo "Retrieval eval: ${AUTORESEARCH_RETRIEVAL_REPORT}"
  echo "Train log: ${TRAIN_LOG}"
  echo "Judge log: ${JUDGE_LOG}"
fi
