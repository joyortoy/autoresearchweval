#!/usr/bin/env bash
set -euo pipefail

notify_discord() {
  local title="$1"
  local body="${2:-}"
  if [[ -z "${AUTORESEARCH_DISCORD_WEBHOOK_URL:-}" ]]; then
    return 0
  fi
  AUTORESEARCH_DISCORD_WEBHOOK_URL="${AUTORESEARCH_DISCORD_WEBHOOK_URL}" \
  AUTORESEARCH_DISCORD_USERNAME="${AUTORESEARCH_DISCORD_USERNAME:-autoresearch}" \
  AUTORESEARCH_DISCORD_AVATAR_URL="${AUTORESEARCH_DISCORD_AVATAR_URL:-}" \
  RUN_NAME="${RUN_NAME:-}" \
  RUN_MODE="${RUN_MODE:-}" \
  OPTIONAL_MEMORY_ADAPTER_MODEL_INTENT="${OPTIONAL_MEMORY_ADAPTER_MODEL_INTENT:-}" \
  OPTIONAL_MEMORY_ADAPTER_MODEL_MEMORY_AGENT="${OPTIONAL_MEMORY_ADAPTER_MODEL_MEMORY_AGENT:-}" \
  LOG_DIR="${LOG_DIR:-}" \
  TITLE="${title}" \
  BODY="${body}" \
  python3 - <<'PY' >/dev/null 2>&1 || true
import json, os, urllib.request
url = os.environ.get("AUTORESEARCH_DISCORD_WEBHOOK_URL", "").strip()
if not url:
    raise SystemExit(0)
lines = [
    f"run: `{os.environ.get('RUN_NAME','').strip()}`",
    f"mode: `{os.environ.get('RUN_MODE','').strip()}`",
    f"adapter_intent: `{os.environ.get('OPTIONAL_MEMORY_ADAPTER_MODEL_INTENT','').strip()}`",
    f"adapter_memory_agent: `{os.environ.get('OPTIONAL_MEMORY_ADAPTER_MODEL_MEMORY_AGENT','').strip()}`",
]
if os.environ.get("LOG_DIR", "").strip():
    lines.append(f"log_dir: `{os.environ.get('LOG_DIR').strip()}`")
if os.environ.get("BODY", "").strip():
    lines.append(os.environ.get("BODY", "").strip())
payload = {"username": os.environ.get("AUTORESEARCH_DISCORD_USERNAME", "autoresearch"), "content": f"**{os.environ.get('TITLE','').strip()}**\n" + "\n".join(lines)}
avatar = os.environ.get("AUTORESEARCH_DISCORD_AVATAR_URL", "").strip()
if avatar:
    payload["avatar_url"] = avatar
req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as resp:
    resp.read()
PY
}
