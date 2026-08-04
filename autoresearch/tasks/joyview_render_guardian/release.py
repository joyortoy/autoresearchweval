from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def write_release_manifest(
    *,
    cfg: Any,
    outcome: dict[str, Any],
    train_result: dict[str, Any],
    eval_result: dict[str, Any],
    release_root: str | Path = "releases/render_guardian",
) -> dict[str, Any]:
    root = Path(release_root)
    root.mkdir(parents=True, exist_ok=True)
    status = outcome.get("status")
    promote = status == "keep" and outcome.get("trust_decision") in {"auto_promote", "limited_canary"}
    artifact_dir = Path(train_result.get("checkpoint_dir") or root / "candidates" / "none")
    checksum = _dir_checksum(artifact_dir)
    manifest = {
        "schema": "joyview.model-release-manifest/v1",
        "model_id": f"render-guardian-{(train_result.get('config_hash') or 'unknown')}",
        "parent_model": os.getenv("RENDER_GUARDIAN_PARENT_MODEL", "incumbent"),
        "dataset_hash": (train_result.get("dataset_hash") or eval_result.get("dataset_hash") or "unknown"),
        "teacher_model": os.getenv("RENDER_GUARDIAN_TEACHER_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
        "teacher_revision": os.getenv("RENDER_GUARDIAN_TEACHER_REVISION", "main"),
        "prompt_version": "rg-teacher-v1",
        "student_model": os.getenv("RENDER_GUARDIAN_STUDENT_MODEL", "HuggingFaceTB/SmolVLM-256M-Instruct"),
        "training_config_hash": train_result.get("config_hash"),
        "code_commit": _git_head(cfg.root_dir),
        "metrics": eval_result.get("metrics") or {},
        "trust_decision": outcome.get("trust_decision"),
        "trust_score": outcome.get("trust_score"),
        "release_status": "promoted" if promote else "discarded",
        "rollback_target": os.getenv("RENDER_GUARDIAN_ROLLBACK_TARGET", "incumbent"),
        "artifact_checksum": checksum,
        "artifact_path": str(artifact_dir),
        "supported_contract_versions": ["joyview.render-adjustment/v1"],
        "supported_device_tiers": ["low", "mid", "high"],
        "lineage_id": outcome.get("lineage_id") or getattr(cfg, "lineage_id", None),
        "weights_committed_to_git": False,
    }
    out = root / f"{manifest['model_id']}.manifest.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    out.write_text(text, encoding="utf-8")
    manifest["manifest_path"] = str(out)
    manifest["manifest_checksum"] = hashlib.sha256(text.encode()).hexdigest()
    if promote:
        promoted = root / "PROMOTED.manifest.json"
        promoted.write_text(text, encoding="utf-8")
        manifest["promoted_path"] = str(promoted)
    return manifest


def _dir_checksum(path: Path) -> str:
    h = hashlib.sha256()
    if not path.exists():
        return h.hexdigest()
    if path.is_file():
        h.update(path.read_bytes())
        return h.hexdigest()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(path).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def _git_head(root: str) -> str:
    try:
        import subprocess

        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        return (cp.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"
