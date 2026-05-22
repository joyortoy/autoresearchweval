from __future__ import annotations

import math
from .telemetry_types import DriftTelemetry


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _l2(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compute_drift_metrics(
    baseline_embedding: list[float],
    candidate_embedding: list[float],
    baseline_hidden: list[float] | None = None,
    candidate_hidden: list[float] | None = None,
    baseline_entropy: float | None = None,
    candidate_entropy: float | None = None,
    previous_drift: float = 0.0,
    previous_velocity: float = 0.0,
) -> DriftTelemetry:
    cos = _cosine(baseline_embedding, candidate_embedding)
    emb_shift = 1.0 - cos
    rep_div = _l2(baseline_embedding, candidate_embedding)

    hidden_sim = 1.0
    if baseline_hidden is not None and candidate_hidden is not None:
        hidden_sim = _cosine(baseline_hidden, candidate_hidden)

    entropy_shift = 0.0
    if baseline_entropy is not None and candidate_entropy is not None:
        entropy_shift = candidate_entropy - baseline_entropy

    semantic_direction_change = (emb_shift * 0.7) + ((1.0 - hidden_sim) * 0.3)
    drift_score = max(0.0, semantic_direction_change + abs(entropy_shift) * 0.1)
    drift_delta = drift_score - previous_drift
    velocity = drift_delta
    acceleration = velocity - previous_velocity

    reasons: list[str] = []
    if emb_shift > 0.25:
        reasons.append("DRIFT_EMBEDDING_SHIFT_HIGH")
    if hidden_sim < 0.7:
        reasons.append("DRIFT_HIDDEN_SIM_LOW")
    if abs(entropy_shift) > 0.4:
        reasons.append("DRIFT_ENTROPY_SHIFT_HIGH")

    return DriftTelemetry(
        embedding_cosine_shift=emb_shift,
        representation_divergence=rep_div,
        hidden_state_similarity=hidden_sim,
        semantic_direction_change=semantic_direction_change,
        attention_entropy_shift=entropy_shift,
        representation_drift_score=drift_score,
        attention_drift_delta=drift_delta,
        cumulative_attention_drift=previous_drift + max(0.0, drift_score),
        drift_velocity=velocity,
        drift_acceleration=acceleration,
        drift_reason_codes=reasons,
    )
