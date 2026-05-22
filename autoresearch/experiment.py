from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .evaluator import metric_status
from .state import append_result_row, best_kept_val_bpb
from .trainer import run_training
from .trust_gate import apply_trust


@dataclass
class RunOutcome:
    status: str
    val_bpb: str
    memory_gb: str
    trust_decision: str
    trust_score: float | None
    hard_fail_reasons: list[str]
    description: str
    lineage_id: str
    parent_run_id: str | None
    ancestor_hash: str
    policy_version: str
    policy_hash: str
    cumulative_attention_drift: float
    drift_velocity: float
    drift_acceleration: float
    lineage_drift_history: list[float]


def run_once(cfg: Any, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        trust = apply_trust(
            cfg.policy,
            cfg.trust_log,
            {
                "val_bpb": "0.99",
                "best_before": "1.0",
                "metric_status": "keep",
                "memory_gb": "40",
            },
        )
        append_result_row(cfg.results_tsv, "dryrun", "0.990000", "40.0", trust.get("status", "discard"), "dry-run")
        return asdict(
            RunOutcome(
                status=trust.get("status", "discard"),
                val_bpb="0.990000",
                memory_gb="40.0",
                trust_decision=trust.get("decision", "rollback"),
                trust_score=trust.get("trust_score"),
                hard_fail_reasons=trust.get("hard_fail_reasons", []),
                description="dry-run",
                lineage_id=cfg.lineage_id,
                parent_run_id=cfg.parent_run_id,
                ancestor_hash=cfg.ancestor_hash,
                policy_version=cfg.policy_version,
                policy_hash=cfg.policy_hash,
                cumulative_attention_drift=cfg_float("AUTORESEARCH_CUMULATIVE_ATTENTION_DRIFT", 0.0),
                drift_velocity=cfg_float("AUTORESEARCH_DRIFT_VELOCITY", 0.0),
                drift_acceleration=cfg_float("AUTORESEARCH_DRIFT_ACCELERATION", 0.0),
                lineage_drift_history=[],
            )
        )

    rc, val, peak, _stdout = run_training(cfg.train_log)
    if rc != 0 or not val or not peak:
        append_result_row(cfg.results_tsv, "nogit", "0.000000", "0.0", "crash", "train-crash")
        return asdict(
            RunOutcome(
                status="crash",
                val_bpb="0.000000",
                memory_gb="0.0",
                trust_decision="rollback",
                trust_score=None,
                hard_fail_reasons=["TRAIN_CRASH"],
                description="train-crash",
                lineage_id=cfg.lineage_id,
                parent_run_id=cfg.parent_run_id,
                ancestor_hash=cfg.ancestor_hash,
                policy_version=cfg.policy_version,
                policy_hash=cfg.policy_hash,
                cumulative_attention_drift=0.0,
                drift_velocity=0.0,
                drift_acceleration=0.0,
                lineage_drift_history=[],
            )
        )

    try:
        memory_gb = f"{float(peak) / 1024.0:.1f}"
    except Exception:
        memory_gb = "0.0"

    best_before = best_kept_val_bpb(cfg.results_tsv)
    status = metric_status(val, best_before)
    trust = apply_trust(
        cfg.policy,
        cfg.trust_log,
        {
            "val_bpb": val,
            "best_before": best_before,
            "memory_gb": memory_gb,
            "metric_status": status,
            "attention_direction_score": cfg_float("AUTORESEARCH_ATTENTION_DIRECTION_SCORE", 50.0),
            "intended_attention_similarity": cfg_float("AUTORESEARCH_INTENDED_ATTENTION_SIMILARITY", 0.5),
            "unsafe_attention_similarity": cfg_float("AUTORESEARCH_UNSAFE_ATTENTION_SIMILARITY", 0.5),
            "attention_margin": cfg_float("AUTORESEARCH_ATTENTION_MARGIN", 0.0),
            "attention_drift_delta": cfg_float("AUTORESEARCH_ATTENTION_DRIFT_DELTA", 0.0),
            "unsafe_attention_pull": cfg_float("AUTORESEARCH_UNSAFE_ATTENTION_PULL", 0.0),
            "representation_drift_score": cfg_float("AUTORESEARCH_REPRESENTATION_DRIFT_SCORE", 0.0),
            "cumulative_attention_drift": cfg_float("AUTORESEARCH_CUMULATIVE_ATTENTION_DRIFT", 0.0),
            "drift_velocity": cfg_float("AUTORESEARCH_DRIFT_VELOCITY", 0.0),
            "drift_acceleration": cfg_float("AUTORESEARCH_DRIFT_ACCELERATION", 0.0),
            "embedding_cosine_shift": cfg_float("AUTORESEARCH_EMBEDDING_COSINE_SHIFT", 0.0),
            "semantic_direction_change": cfg_float("AUTORESEARCH_SEMANTIC_DIRECTION_CHANGE", 0.0),
            "attention_entropy_shift": cfg_float("AUTORESEARCH_ATTENTION_ENTROPY_SHIFT", 0.0),
            "policy_version": cfg.policy_version,
            "policy_hash": cfg.policy_hash,
        },
    )
    final_status = trust.get("status", "discard")
    append_result_row(cfg.results_tsv, "nogit", val, memory_gb, final_status, "autoresearch-run")
    return asdict(
        RunOutcome(
            status=final_status,
            val_bpb=val,
            memory_gb=memory_gb,
            trust_decision=trust.get("decision", "rollback"),
            trust_score=trust.get("trust_score"),
            hard_fail_reasons=trust.get("hard_fail_reasons", []),
            description="autoresearch-run",
            lineage_id=cfg.lineage_id,
            parent_run_id=cfg.parent_run_id,
            ancestor_hash=cfg.ancestor_hash,
            policy_version=cfg.policy_version,
            policy_hash=cfg.policy_hash,
            cumulative_attention_drift=cfg_float("AUTORESEARCH_CUMULATIVE_ATTENTION_DRIFT", 0.0),
            drift_velocity=cfg_float("AUTORESEARCH_DRIFT_VELOCITY", 0.0),
            drift_acceleration=cfg_float("AUTORESEARCH_DRIFT_ACCELERATION", 0.0),
            lineage_drift_history=[cfg_float("AUTORESEARCH_CUMULATIVE_ATTENTION_DRIFT", 0.0)],
        )
    )


def cfg_float(name: str, default: float) -> float:
    import os
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default
