# autoresearch

Autoresearch is a **Python-first experimental alignment/governance framework for autonomous LLM experimentation**.

## What this is

A local-first, prototype-scoped system for bounded autonomous model iteration with policy-gated governance.

Core concerns:
- bounded train/evaluate loops,
- trust-aware promotion,
- fail-closed governance,
- rollback semantics,
- lineage/provenance tracking,
- attention-direction and representation telemetry (experimental).

## Core flow

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

## Attention-Direction Governance

This project treats alignment as attention-direction awareness during bounded experimentation.

The governance layer monitors whether representation/attention appears to move toward an intended alignment direction or toward unsafe attention directions.

Attention drift may provide early warning signals before obviously harmful output appears, but this is still an experimental interpretability-inspired signal.

**This project explores whether representation-space telemetry and attention-direction signals can contribute useful governance information during bounded autonomous model iteration.**

**This repository does not claim that attention telemetry alone can reliably determine alignment or safety.**

**Attention-direction governance remains an experimental research area requiring empirical validation.**

## Telemetry and calibration

Telemetry layer (lightweight, backend-agnostic):
- `telemetry/representation_probe.py`
- `telemetry/drift_metrics.py`
- `telemetry/telemetry_types.py`

Calibration artifacts:
- `experiments/calibration/` prompt sets + `run_calibration.py`
- `examples/drift_cases/` illustrative drift patterns

These are prototype research tools, not validated guarantees.

## Trust governance

Trust scoring (`trust_score.py`) + policy (`trust_policy.json`) supports:
- metric-discard override enforcement,
- hard-fail discard semantics,
- fail-closed fallback,
- optional telemetry-informed penalties/warnings.

## Why bounded iteration?

Bounded iteration is itself a governance primitive:
- constrains runaway optimization pressure,
- improves run comparability,
- enables gradual trust escalation,
- makes rollback and lineage reasoning tractable.

## What this is not

- not solved alignment,
- not AGI safety,
- not production superalignment,
- not a claim of reliable internal alignment detection.

## Quickstart

```bash
make demo
make test
make lint-shell
```

Trust sample only:

```bash
make trust-sample
```

Optional local training (requires NVIDIA GPU + prepared data):

```bash
uv run prepare.py
uv run train.py
```

Python orchestrator:

```bash
python3 -m autoresearch.orchestrator --dry-run
```

Shell compatibility wrapper:

```bash
./run_intent_autoresearch.sh --dry-run
```

## Documentation

- `docs/architecture.md`
- `docs/trust_governance.md`
- `docs/threat_model.md`
- `docs/calibration.md`
- `docs/open_source_boundary.md`

## License

MIT
