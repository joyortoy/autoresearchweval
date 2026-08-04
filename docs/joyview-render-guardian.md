# JoyView Render Guardian task profile

Task id: `joyview_render_guardian`

This profile plugs into the existing autoresearch orchestrator. It does **not** replace trust scoring, keep/discard, rollback, or lineage.

## Loop

```text
proposal -> teacher label (Qwen-VL) -> student train (SmolVLM) -> evaluate
 -> telemetry/metrics -> trust_score.py / trust_policy.json -> keep|discard
 -> rollback target -> release manifest -> lineage log
```

## Commands

```bash
make render-guardian-demo
make render-guardian-test
make render-guardian-smoke
make render-guardian-env-check
make render-guardian-autoresearch
```

Dry-run exercises the full governed loop without GPU training.

## Models

- Teacher default: `Qwen/Qwen2.5-VL-7B-Instruct` (`RENDER_GUARDIAN_TEACHER_MODEL`)
- Student default: `HuggingFaceTB/SmolVLM-256M-Instruct` (`RENDER_GUARDIAN_STUDENT_MODEL`)

Real training is fail-closed unless CUDA + deps are present and explicitly enabled on the 5090 host.

## Related docs

- [Governance](./render-guardian-governance.md)
- [Evaluation](./render-guardian-evaluation.md)
- [Lineage](./render-guardian-lineage.md)
- [Release](./render-guardian-release.md)
