from __future__ import annotations

import argparse
import json
from typing import Any

from .config import load_config
from .experiment import run_once
from .notify import notify
from .state import ensure_dirs, save_run_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Python-first orchestrator with shell wrapper compatibility.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without training; exercises trust-gate and result logging.")
    parser.add_argument("--config", default="", help="Reserved for future config-file support.")
    parser.add_argument("--policy", default="trust_policy.json", help="Path to trust policy JSON.")
    parser.add_argument("--metrics", default="", help="Reserved for future external metrics ingestion.")
    parser.add_argument("--run-name", default="", help="Optional explicit run name.")
    parser.add_argument("--enable-optional-evals", action="store_true", help="Reserved optional plugin switch (disabled by default).")
    parser.add_argument("--notify", action="store_true", help="Emit lightweight local notifications.")
    parser.add_argument("--human-review-checkpoint", action="store_true", help="Mark this run as requiring human governance checkpoint.")
    parser.add_argument("--enable-adversarial-eval-adapter", action="store_true", help="Optional adversarial evaluation hook flag (interface only).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args)
    ensure_dirs(cfg.log_dir)
    notify(cfg.notify, "autoresearch orchestrator start", cfg.run_name)
    result: dict[str, Any] = run_once(cfg, dry_run=args.dry_run)
    result["human_governance_checkpoint"] = bool(args.human_review_checkpoint)
    result["adversarial_eval_adapter_enabled"] = bool(args.enable_adversarial_eval_adapter)
    result["policy_approved_by"] = cfg.policy_approved_by
    result["policy_change_requires_review"] = cfg.policy_change_requires_review
    save_run_summary(f"{cfg.log_dir}/{cfg.run_name}_summary.json", result)
    notify(cfg.notify, "autoresearch orchestrator finish", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
