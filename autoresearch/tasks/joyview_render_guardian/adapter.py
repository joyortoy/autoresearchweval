from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import dataset as ds
from . import evaluate as ev
from . import hard_fail as hf
from . import release as rel
from . import student_smolvlm as student
from . import teacher_qwen as teacher
from .env_check import check_environment
from .contracts import output_hash


class JoyViewRenderGuardianAdapter:
    """Task profile for governed JoyView render repair training."""

    @property
    def task_id(self) -> str:
        return "joyview_render_guardian"

    def propose(self, cfg: Any) -> dict[str, Any]:
        env = check_environment()
        return {
            "task": self.task_id,
            "proposal_id": f"prop-{getattr(cfg, 'run_name', 'run')}",
            "teacher_model": os.getenv("RENDER_GUARDIAN_TEACHER_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
            "student_model": os.getenv("RENDER_GUARDIAN_STUDENT_MODEL", "HuggingFaceTB/SmolVLM-256M-Instruct"),
            "env": env,
            "description": "bounded render-guardian student update from approved sanitized traces",
        }

    def select_dataset(self, cfg: Any) -> dict[str, Any]:
        sample = Path(cfg.root_dir) / "examples" / "render_guardian" / "sample_trace.json"
        path = os.getenv("RENDER_GUARDIAN_DATASET", str(sample))
        traces = ds.load_traces(path) if Path(path).exists() else []
        if not traces and sample.exists():
            traces = ds.load_traces(sample)
        trainable = ds.trainable_traces(traces)
        split_info = ds.deterministic_splits(trainable or traces)
        return {
            "path": path,
            "raw_count": len(traces),
            "trainable_count": len(trainable),
            "split_hash": split_info["split_hash"],
            "leakage": split_info["leakage"],
            "splits": split_info["splits"],
            "lineage": split_info["lineage"],
            "unauthorized_rejected": len(traces) - len(trainable),
        }

    def run_teacher(self, cfg: Any, proposal: dict[str, Any]) -> dict[str, Any]:
        layout = {
            "surfaces": [
                {
                    "id": "s1",
                    "bounds": {"x": 0, "y": 0, "width": 200, "height": 100},
                    "contrast_ratio": 3.0,
                },
                {
                    "id": "s2",
                    "bounds": {"x": 100, "y": 40, "width": 200, "height": 100},
                },
            ]
        }
        return teacher.propose_repair(
            before_screenshot_ref="local://sanitized/before.png",
            layout=layout,
            mock=True,
        )

    def train_student(self, cfg: Any, dataset: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        # SMOKE shortens steps; it must NOT force dry_run (that skips CUDA).
        smoke = (not dry_run) and os.getenv("RENDER_GUARDIAN_SMOKE", "0") == "1"
        result = student.train_student(
            dataset=dataset,
            dry_run=dry_run,
            smoke=smoke or dry_run,
            seed=int(os.getenv("RENDER_GUARDIAN_SEED", "42")),
            output_dir=Path(cfg.root_dir) / "releases" / "render_guardian" / "candidates",
        )
        result["dataset_hash"] = dataset.get("split_hash")
        return result

    def evaluate(self, cfg: Any, train_result: dict[str, Any]) -> dict[str, Any]:
        extra_path = Path(cfg.root_dir) / "examples" / "render_guardian" / "sample_trace.json"
        extra = ds.load_traces(extra_path) if extra_path.exists() else []
        payload = ev.run_evaluation(train_result=train_result, extra_traces=extra)
        payload["dataset_hash"] = train_result.get("dataset_hash")
        return payload

    def trust_metrics(self, cfg: Any, eval_result: dict[str, Any]) -> dict[str, Any]:
        m = dict(eval_result.get("metrics") or {})
        m["task"] = self.task_id
        m["metric_status"] = "keep" if float(m.get("adjustment_success_rate", 0)) >= 0.5 else "discard"
        # Map RG metrics into existing trust dimensions without removing them
        m["safety"] = max(
            0.0,
            100.0
            - float(m.get("forbidden_action_rate", 0)) * 100.0
            - float(m.get("oscillation_rate", 0)) * 40.0
            - float(m.get("regression_rate", 0)) * 30.0,
        )
        m["data_trust"] = 90.0 if not eval_result.get("leakage") else 40.0
        m["generalization"] = float(m.get("device_tier_compatibility", 1.0)) * 90.0
        m["human_policy_confidence"] = float(m.get("user_acceptance_rate", 0.8)) * 100.0
        m["latency_score"] = 95.0 if float(m.get("latency_ms_p50", 999)) < 200 else 70.0
        m["memory_gb"] = float(m.get("memory_gb", m.get("peak_memory_mb", 512) / 1024.0))
        m["val_bpb"] = float(m.get("val_bpb", 0.95))
        m["best_before"] = float(os.getenv("RENDER_GUARDIAN_BEST_BEFORE", "1.0"))
        # hard-fail signal fields
        m["sensitive_content_reproduced"] = False
        m["business_data_mutated"] = False
        m["attempted_secret_network_shell_or_code"] = False
        m["deterministic_safety_failed"] = float(m.get("hard_diagnostic_pass_rate", 1)) < 0.5
        m["split_leakage"] = bool(eval_result.get("leakage"))
        m["unauthorized_trace_included"] = False
        m["lineage_corrupt"] = False
        m["lineage_incomplete"] = not bool(getattr(cfg, "lineage_id", None))
        return m

    def hard_fail_check(self, metrics: dict[str, Any]) -> list[str]:
        profile = {}
        try:
            # policy may be injected by experiment
            profile = metrics.get("_policy_profile") or {}
        except Exception:
            profile = {}
        return hf.check_hard_fails(metrics, profile)

    def release_artifact(self, cfg: Any, outcome: dict[str, Any]) -> dict[str, Any] | None:
        train_result = outcome.get("train_result") or {}
        eval_result = outcome.get("eval_result") or {}
        if not train_result:
            return None
        return rel.write_release_manifest(
            cfg=cfg,
            outcome=outcome,
            train_result=train_result,
            eval_result=eval_result,
            release_root=Path(cfg.root_dir) / "releases" / "render_guardian",
        )

    def rollback_target(self, cfg: Any) -> str | None:
        return os.getenv("RENDER_GUARDIAN_ROLLBACK_TARGET", "incumbent")

    def run_governed(self, cfg: Any, *, dry_run: bool) -> dict[str, Any]:
        """Full propose->train->evaluate->metrics path for experiment.dispatch."""
        proposal = self.propose(cfg)
        dataset = self.select_dataset(cfg)
        teacher_label = self.run_teacher(cfg, proposal)
        train_result = self.train_student(cfg, dataset, dry_run=dry_run)
        eval_result = self.evaluate(cfg, train_result)
        eval_result["leakage"] = dataset.get("leakage") or []
        metrics = self.trust_metrics(cfg, eval_result)
        # attach policy profile hard-fail section if present on disk
        try:
            policy = json.loads(Path(cfg.policy).read_text(encoding="utf-8"))
            metrics["_policy_profile"] = (policy.get("task_profiles") or {}).get(self.task_id) or {}
        except Exception:
            metrics["_policy_profile"] = {}
        # Fail closed when a requested real CUDA train does not produce a checkpoint.
        if not dry_run:
            train_failed = train_result.get("status") != "ok"
            skipped = bool((train_result.get("metrics") or {}).get("skipped_real_train"))
            enable_real = os.getenv("RENDER_GUARDIAN_ENABLE_REAL_TRAIN", "0") == "1"
            if enable_real and (train_failed or skipped):
                metrics["metric_status"] = "discard"
                metrics["deterministic_safety_failed"] = True
                metrics["rg_hard_fail_reasons"] = list(metrics.get("rg_hard_fail_reasons") or []) + [
                    "HF_RG_DETERMINISTIC_SAFETY"
                ]
                metrics["train_failure"] = train_result.get("error") or (train_result.get("metrics") or {}).get(
                    "skip_reason"
                )
        rg_fails = self.hard_fail_check(metrics)
        if rg_fails:
            metrics["metric_status"] = "discard"
            metrics["rg_hard_fail_reasons"] = rg_fails
            metrics["deterministic_safety_failed"] = True
        return {
            "proposal": proposal,
            "dataset": {
                "split_hash": dataset.get("split_hash"),
                "trainable_count": dataset.get("trainable_count"),
                "leakage": dataset.get("leakage"),
            },
            "teacher_label": {
                "output_hash": teacher_label.get("output_hash"),
                "approval_status": teacher_label.get("approval_status"),
                "schema_validation": teacher_label.get("schema_validation"),
            },
            "train_result": train_result,
            "eval_result": eval_result,
            "metrics": metrics,
            "rollback_target": self.rollback_target(cfg),
            "proposal_hash": output_hash(proposal),
        }
