from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepresentationSnapshot:
    embedding: list[float]
    hidden_state: list[float] | None = None
    attention_entropy: float | None = None
    semantic_label: str = "unknown"


@dataclass
class DriftTelemetry:
    embedding_cosine_shift: float = 0.0
    representation_divergence: float = 0.0
    hidden_state_similarity: float = 1.0
    semantic_direction_change: float = 0.0
    attention_entropy_shift: float = 0.0
    representation_drift_score: float = 0.0
    attention_drift_delta: float = 0.0
    cumulative_attention_drift: float = 0.0
    drift_velocity: float = 0.0
    drift_acceleration: float = 0.0
    drift_reason_codes: list[str] = field(default_factory=list)
    semantic_anchor_examples: list[str] = field(default_factory=list)
    nearest_behavior_reference: str = ""
