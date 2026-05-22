# Threat Model (Prototype Scope)

This framework is a bounded, experimental governance system. It does not claim solved alignment.

## Core threats
- reward hacking
- semantic deception
- latent harmful drift
- eval gaming
- poisoning
- policy evasion
- alignment faking
- rollback bypass
- trust-score gaming
- adversarial semantic steering

## Representation telemetry-specific threat insights

### False confidence from telemetry
- Meaning: drift metrics look stable while harmful behavior still exists.
- Partial mitigation: trust metrics are advisory and combined with hard-fail/other checks.
- Limitation: no validated guarantee telemetry captures all unsafe internal movement.
- Future work: stronger calibration datasets and adversarial probes.

### Over-penalizing benign novelty
- Meaning: creative but safe behavior appears as drift.
- Partial mitigation: optional metrics, conservative penalties, human checkpoint semantics.
- Limitation: calibration may be insufficient for domain-shift contexts.
- Future work: ambiguity-aware calibration sets.

### Slow lineage degradation
- Meaning: risky behavior emerges gradually across many small runs.
- Partial mitigation: lineage/provenance + longitudinal drift fields.
- Limitation: no automated long-horizon risk classifier yet.
- Future work: ancestry-aware trend alarms and rollback heuristics.

## Honest scope

Attention-direction governance remains experimental and interpretability-inspired.
This repository does not claim that attention telemetry alone can reliably determine alignment or safety.
