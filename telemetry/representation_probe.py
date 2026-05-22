from __future__ import annotations

from .drift_metrics import compute_drift_metrics
from .telemetry_types import DriftTelemetry, RepresentationSnapshot


class RepresentationProbe:
    """Backend-agnostic representation telemetry probe.

    Expected inputs are embedding/hidden-state vectors extracted by caller-side model adapters.
    This module does not assume a specific model backend.
    """

    def compare(
        self,
        baseline: RepresentationSnapshot,
        candidate: RepresentationSnapshot,
        previous_drift: float = 0.0,
        previous_velocity: float = 0.0,
    ) -> DriftTelemetry:
        out = compute_drift_metrics(
            baseline_embedding=baseline.embedding,
            candidate_embedding=candidate.embedding,
            baseline_hidden=baseline.hidden_state,
            candidate_hidden=candidate.hidden_state,
            baseline_entropy=baseline.attention_entropy,
            candidate_entropy=candidate.attention_entropy,
            previous_drift=previous_drift,
            previous_velocity=previous_velocity,
        )
        out.semantic_anchor_examples = [baseline.semantic_label, candidate.semantic_label]
        out.nearest_behavior_reference = candidate.semantic_label
        return out
