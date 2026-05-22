#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from telemetry.representation_probe import RepresentationProbe
from telemetry.telemetry_types import RepresentationSnapshot

ROOT = Path(__file__).resolve().parent


def _load(name: str) -> list[str]:
    return json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))


def _mock_snapshot(prompt: str, label: str) -> RepresentationSnapshot:
    # Mock embedding for prototype calibration: deterministic from text length/chars.
    base = float(len(prompt))
    vec = [((ord(c) % 17) / 17.0) for c in prompt[:16]]
    while len(vec) < 16:
        vec.append((base % 13) / 13.0)
    return RepresentationSnapshot(embedding=vec, hidden_state=vec[:], attention_entropy=(base % 10) / 10.0, semantic_label=label)


def main() -> int:
    probe = RepresentationProbe()
    baseline = _mock_snapshot("safe baseline behavior", "safe_baseline")
    report: dict[str, list[dict]] = {}

    for split in ["safe_prompts", "unsafe_prompts", "ambiguous_prompts", "deceptive_prompts"]:
        items = _load(split)
        rows = []
        prev_drift = 0.0
        prev_vel = 0.0
        for text in items:
            snap = _mock_snapshot(text, split)
            t = probe.compare(baseline, snap, previous_drift=prev_drift, previous_velocity=prev_vel)
            prev_drift = t.cumulative_attention_drift
            prev_vel = t.drift_velocity
            rows.append(t.__dict__)
        report[split] = rows

    out = ROOT / "calibration_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
