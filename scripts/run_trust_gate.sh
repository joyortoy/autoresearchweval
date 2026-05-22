#!/usr/bin/env bash
set -euo pipefail

run_trust_gate() {
  local log_dir="$1" run_name="$2" val_bpb="$3" best_before="$4" memory_gb="$5" judge_verdict="$6" metric_status="$7" trust_log="$8" root_dir="$9"
  python3 - "${val_bpb}" "${best_before}" "${memory_gb}" "${judge_verdict}" "${metric_status}" <<'PY' > "${log_dir}/${run_name}_trust_input.json"
import json, sys
val_bpb, best_before, memory_gb, judge_verdict, metric_status = sys.argv[1:6]
print(json.dumps({"val_bpb": val_bpb, "best_before": best_before or None, "memory_gb": memory_gb, "judge_verdict": judge_verdict, "metric_status": metric_status}, indent=2))
PY
  if uv run python trust_score.py --policy trust_policy.json --metrics-json "${log_dir}/${run_name}_trust_input.json" --output-json "${trust_log}" >/tmp/autoresearch_trust_stdout.log 2>&1; then
    python3 - "${trust_log}" <<'PY'
import json, sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
print(x.get('status',''))
print(x.get('decision',''))
print(x.get('trust_score',''))
print(','.join(x.get('hard_fail_reasons',[])))
PY
  else
    python3 "${root_dir}/scripts/write_trust_fallback.py" "${trust_log}"
    printf "discard\nrollback\n\nTRUST_SCORER_UNAVAILABLE\n"
  fi
}
