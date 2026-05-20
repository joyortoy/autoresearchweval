# Autoresearch Crash Report

Date: 2026-03-17
Host timezone used in evidence: Asia/Singapore (+08)

## Executive Summary

The strongest evidence points to repeated GPU-side failures in the intent/OpenClaw path, not in the PyTorch training loop itself. The original `autoresearch` runs on March 13, 2026 repeatedly hit `node-llama-cpp` CUDA faults during qmd embedding and reranking, including:

- `CUDA error: the launch timed out and was terminated`
- `CUDA error: an internal operation failed`

The final `autoresearch` run on March 15, 2026 ended abnormally: its train log was cut off mid-run and never printed the normal footer metrics, which is consistent with the host rebooting or hard-locking before the process could exit cleanly.

I could not read kernel `dmesg` or full kernel journal from this session, so the exact kernel-level trigger is not proven. After moving the checks outside the sandbox, the host GPU and local services are healthy:

- `nvidia-smi` is healthy on the host
- PyTorch CUDA initializes successfully on the host
- the patched smoke path succeeds outside the sandbox

Based on the historical logs plus the isolated reproductions below, the most likely root cause is still the intent/qmd `node-llama-cpp` CUDA workload on the RTX 5090, but the failure appears intermittent and state/load dependent rather than a deterministic always-fails path.

## Confirmed Evidence

### 1. The original autoresearch loop is an infinite restart loop

File: `/home/sam/projects/autoresearch/run_forever_intent_autoresearch.sh`

- Lines 20-30 run `while true` forever.
- Each cycle launches `run_intent_autoresearch.sh full`.
- There is only a 15 second sleep between runs.

This means the machine can remain under near-continuous GPU load for hours.

### 2. The PyTorch training path already disables risky Blackwell features by default

File: `/home/sam/projects/autoresearch/train.py`

- Lines 50-54 disable FlashAttention and default `torch.compile` on `sm_120` / Blackwell-class GPUs.

This makes the training path less likely to be the direct crash source than the separate intent/qmd CUDA stack.

### 3. Repeated CUDA failures appear in the intent logs

Representative files:

- `/home/sam/projects/autoresearch/logs/autoresearch_20260313_004637_intent.log`
- `/home/sam/projects/autoresearch/logs/autoresearch_20260313_004734_intent.log`
- `/home/sam/projects/autoresearch/logs/autoresearch_20260313_004807_intent.log`
- `/home/sam/projects/autoresearch/logs/autoresearch_20260313_043218_intent.log`

Observed failures include:

- `node-llama-cpp` CUDA launch timeout
- `ggml-cuda` internal operation failure
- `cublasGemmBatchedEx(...)` failures during embedding/reranking

These errors occur during the OpenClaw/qmd retrieval path, not during the PyTorch training loop.

### 4. The last autoresearch training log was truncated

Files:

- `/home/sam/projects/autoresearch/logs/autoresearch_20260315_015338_train.log`
- `/home/sam/projects/autoresearch/logs/autoresearch_20260315_010649_train.log`

Evidence:

- `autoresearch_20260315_015338_train.log` has only 16 lines and stops around step 68.
- It does not print the normal footer fields such as `val_bpb`, `training_seconds`, `peak_vram_mb`, or judge output.
- A normal completed run, such as `autoresearch_20260315_005817_train.log`, does print those footer metrics.

This is consistent with abrupt host interruption.

### 5. One of the final intent logs is empty

File:

- `/home/sam/projects/autoresearch/logs/autoresearch_20260315_010713_intent.log`

Evidence:

- File size is `0 bytes`.

That suggests the next cycle started and then was interrupted before it could write output.

### 6. The reboot timeline matches the interrupted run window

From `journalctl --list-boots`:

- Boot `-2` ran from `2026-03-15 00:52:01 +08` to `2026-03-15 01:52:19 +08`
- Boot `-1` started at `2026-03-15 01:53:38 +08`

The final interrupted `autoresearch` logs are timestamped during that same March 15 window, so the reboot happened while that workload family was active.

### 7. Host checks are healthy outside the sandbox

Live checks run on 2026-03-17 outside the sandbox:

- `nvidia-smi` succeeded
- driver version: `580.126.20`
- CUDA version: `13.0`
- GPU: `NVIDIA GeForce RTX 5090`
- PyTorch reported:
  - `cuda_available=True`
  - `device_count=1`
  - `device_name=NVIDIA GeForce RTX 5090`

This means the earlier NVML/CUDA failures seen inside the sandbox were not valid host-level crash evidence.

### 8. The patched smoke path succeeds outside the sandbox

Commands tested:

- `/home/sam/projects/autoresearch/run_intent_autoresearch.sh smoke`
- `OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE=1 /home/sam/projects/autoresearch/run_intent_autoresearch.sh smoke`

Observed behavior:

- memory bridge disabled: success
- memory bridge enabled: success

Outputs:

- `Health check OK: OpenClaw Codex execution assistant is online and ready.`
- `Health check OK: OpenClaw Codex is responsive and memory context routing appears active.`

This shows the crash is not a deterministic one-shot smoke failure.

## Important Naming Trap

The user service named `autoresearch-loop.service` is not running `/home/sam/projects/autoresearch`.

File: `/home/sam/.config/systemd/user/autoresearch-loop.service`

- Line 7 sets `WorkingDirectory=/home/sam/projects/intentautoresearch`
- Line 8 sets `ExecStart=/bin/bash /home/sam/projects/intentautoresearch/run_complex_intent_forever.sh`
- Line 9 sets `Restart=always`

So:

- `autoresearch-loop.service` currently refers to `intentautoresearch`
- the original `autoresearch` project is a different loop and may have been started separately

This can make the crash source easy to misidentify.

## Why OpenClaw Hits qmd / node-llama-cpp

Files:

- `/home/sam/projects/Joyortoy/openclaw/cognition/orchestrator_dynamic.py`
- `/home/sam/projects/Joyortoy/openclaw/cognition/clawvault_client.py`

Behavior:

- OpenClaw enables the memory bridge by default
- `_memory_bridge_text(...)` calls `ClawVault.context(...)`
- `ClawVault.context(...)` shells out to the `clawvault` CLI
- the ClawVault tooling depends on `qmd`

This explains why the OpenClaw smoke path can trigger qmd embedding/query work and therefore `node-llama-cpp` CUDA failures even when the user-facing request looks small.

## Secondary Risk In The Active intentautoresearch Service

File: `/home/sam/projects/intentautoresearch/run_complex_intent_forever.sh`

- Lines 22 and 25 default `AUTO_EXPAND_MAX_STAGE=0` and `AUTO_ADJUST_MODEL_MAX_STAGE=0`
- Lines 192-196 increase minimum embed size, hidden size, max length, and time budget with model stage
- Lines 253-260 run the loop forever

This means the active intentautoresearch service is designed to grow workload over time unless externally bounded.

That said, the user journal currently shows this service with only about `2.3G` peak memory during one long run, so it is not the strongest candidate for the March 15 hard crash.

## Most Likely Root Cause

Most likely cause: repeated CUDA faults in the OpenClaw/qmd `node-llama-cpp` path under certain runtime conditions destabilized the long-running autoresearch loop, and the forever loop kept re-triggering the failing path until the host rebooted or hard-locked.

The failure now looks load- or state-dependent, not constant. The most plausible triggers from the evidence are:

- qmd embedding/reranking activity inside the memory bridge path
- stale or partially embedded qmd index state
- long unattended loops repeatedly re-entering that path
- GPU contention from multiple resident Ollama processes while autoresearch is active

Why this is the leading theory:

- repeated intent-side CUDA failures are explicitly logged
- the PyTorch training path on Blackwell is already in a conservative mode
- the final run ends by truncation, not by a Python exception or graceful failure
- the reboot timeline overlaps the truncated run

## Confidence

Medium.

Reason:

- historical user-space logs strongly support a GPU-side failure chain in qmd / `node-llama-cpp`
- isolated host tests show the failure is intermittent, not always reproducible
- kernel logs were still not accessible here, so I cannot prove the exact NVIDIA Xid / watchdog / kernel event

## Recommended Next Actions

1. Stop the active forever service before more testing:
   `systemctl --user stop autoresearch-loop.service`

2. Do not run the full intent + training loop first. Isolate the components:
   - run the PyTorch training path by itself
   - run the OpenClaw/qmd intent path by itself

3. Prioritize testing without the qmd / `node-llama-cpp` GPU embedding path during unattended runs, because that is where the logged CUDA faults occur.
   - the launcher now defaults `OPENCLAW_ENABLE_INTENT_MEMORY_BRIDGE=0`

4. Collect kernel evidence on the next failure:
   - `journalctl -k -b -1 --no-pager`
   - `dmesg -T | rg 'NVRM|Xid|oom|watchdog|gpu'`

5. Before unattended runs, verify:
   - `nvidia-smi`
   - OpenClaw smoke with memory bridge disabled
   - only then the full autoresearch loop

6. If you want this loop to remain unattended, add hard limits:
   - disable the intent smoke step temporarily
   - cap growth in `intentautoresearch`
   - increase sleep between runs
   - avoid overlapping GPU consumers on the 5090

## Bottom Line

I do not see evidence that the simplified `train.py` alone is what crashed the machine. The logs point much more strongly at the intent retrieval stack hitting repeated qmd / `node-llama-cpp` CUDA faults on the RTX 5090, but the issue is intermittent enough that single smoke runs can still pass.
