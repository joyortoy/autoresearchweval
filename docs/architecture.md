# Architecture

## Framing

Autoresearch is a Python-first, bounded experimentation framework for alignment governance research.

## Core governance flow

```text
proposal
-> train
-> evaluate
-> representation telemetry
-> attention-direction checks
-> calibration signals
-> trust gate
-> keep/discard
-> rollback
-> lineage tracking
-> log
```

## Core modules
- `autoresearch/orchestrator.py`: run lifecycle and CLI.
- `autoresearch/experiment.py`: proposal/train/evaluate/trust/log sequence.
- `autoresearch/trainer.py`: bounded training invocation and metric extraction.
- `autoresearch/state.py`: run summaries, result rows, lineage persistence.
- `trust_score.py`: policy-gated governance scoring and hard-fail decisions.

## Optional plugins
- optional eval adapters
- optional notifications
- optional memory integrations
- optional adversarial evaluation adapter hook

## Telemetry layer (experimental)
- `telemetry/representation_probe.py`
- `telemetry/drift_metrics.py`
- `telemetry/telemetry_types.py`

These provide backend-agnostic interfaces for representation/attention drift signals used in governance research.

## Lineage and provenance

Run summaries track:
- `lineage_id`
- `parent_run_id`
- `ancestor_hash`
- `policy_version`
- `policy_hash`
- drift trend fields (`cumulative_attention_drift`, `drift_velocity`, `drift_acceleration`)

Why lineage matters: harmful behavior can emerge gradually across multiple bounded updates, so governance needs ancestry-aware rollback context.

## Honest scope

This is prototype research infrastructure. It does not claim reliable internal safety detection.
