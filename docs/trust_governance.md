# Trust Governance

`trust_score.py` is a governance interface for bounded autonomous experimentation.

## Inputs and outputs

Input: metrics JSON.  
Output: trust score, component scores, hard-fail reasons, decision, final status (`keep`/`discard`).

## Preserved semantics

- hard-fail rules force discard,
- `metric_status=discard` cannot be overridden,
- scorer failure remains fail-closed (`TRUST_SCORER_UNAVAILABLE` -> discard).

## Attention-direction governance signals

Optional (experimental) telemetry metrics:
- `attention_direction_score`
- `intended_attention_similarity`
- `unsafe_attention_similarity`
- `attention_margin`
- `attention_drift_delta`
- `unsafe_attention_pull`
- `representation_drift_score`
- `cumulative_attention_drift`
- `drift_velocity`
- `drift_acceleration`
- `embedding_cosine_shift`
- `semantic_direction_change`
- `attention_entropy_shift`

These metrics are optional and can:
- contribute lightweight safety/generalization penalties,
- emit warning reason codes,
- trigger hard-fail when configured thresholds are exceeded.

## Policy governance semantics

Policy artifacts are governance-controlled:
- `policy_version`
- `policy_hash`
- `policy_approved_by`
- `policy_change_requires_review`

Governance includes governance of governing rules.

## Human governance checkpoints

Optional human checkpoints include:
- policy approval,
- rollout approval,
- trust override,
- rollback authorization,
- semantic risk review.

## Calibration requirement

These are experimental telemetry signals intended for research and calibration, not validated safety guarantees.
They must be calibrated empirically before being treated as meaningful governance evidence.
