from __future__ import annotations
from dataclasses import dataclass
import os, time, hashlib

@dataclass
class Config:
    root_dir: str
    log_dir: str
    run_name: str
    results_tsv: str
    trust_log: str
    train_log: str
    policy: str
    enable_optional_evals: bool
    notify: bool
    lineage_id: str
    parent_run_id: str | None
    ancestor_hash: str
    policy_version: str
    policy_hash: str
    policy_approved_by: str
    policy_change_requires_review: bool


def load_config(args) -> Config:
    root = os.getcwd()
    log_dir = os.getenv("AUTORESEARCH_LOG_DIR", f"{root}/logs")
    run_name = args.run_name or os.getenv("AUTORESEARCH_RUN_NAME", f"autoresearch_{time.strftime('%Y%m%d_%H%M%S')}")
    policy_path = args.policy
    policy_hash = "unknown"
    policy_version = "unknown"
    try:
        content = open(policy_path, "rb").read()
        policy_hash = hashlib.sha1(content).hexdigest()[:12]
        import json
        policy_version = json.loads(content.decode("utf-8")).get("version", "unknown")
    except Exception:
        pass
    parent_run_id = os.getenv("AUTORESEARCH_PARENT_RUN_ID") or None
    lineage_id = os.getenv("AUTORESEARCH_LINEAGE_ID", f"lin-{run_name}")
    ancestor_hash = hashlib.sha1(f"{parent_run_id or 'root'}:{run_name}".encode("utf-8")).hexdigest()[:12]
    return Config(
        root_dir=root,
        log_dir=log_dir,
        run_name=run_name,
        results_tsv=os.getenv("AUTORESEARCH_RESULTS_TSV", f"{root}/results.tsv"),
        trust_log=f"{log_dir}/{run_name}_trust.json",
        train_log=f"{log_dir}/{run_name}_train.log",
        policy=args.policy,
        enable_optional_evals=bool(args.enable_optional_evals),
        notify=bool(args.notify),
        lineage_id=lineage_id,
        parent_run_id=parent_run_id,
        ancestor_hash=ancestor_hash,
        policy_version=policy_version,
        policy_hash=policy_hash,
        policy_approved_by=os.getenv("AUTORESEARCH_POLICY_APPROVED_BY", "unassigned"),
        policy_change_requires_review=os.getenv("AUTORESEARCH_POLICY_CHANGE_REQUIRES_REVIEW", "1") == "1",
    )
