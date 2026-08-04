from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MIN_EVIDENCE = {
    "consent": True,
    "sanitization_passed": True,
    "user_verdict_in": {"accepted", "edited"},
    "stable": True,
    "schema_valid": True,
}


def load_traces(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if p.is_dir():
        out: list[dict[str, Any]] = []
        for f in sorted(p.glob("*.json")):
            out.append(json.loads(f.read_text(encoding="utf-8")))
        return out
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "traces" in data:
        return list(data["traces"])
    return [data]


def validate_trace(trace: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if trace.get("schema") not in {"joyview.render-training-trace/v1", None}:
        # allow missing schema in fixtures with explicit keys
        if "trace_id" not in trace:
            errors.append("missing_trace_id")
    for key in ("trace_id", "render_id", "user_verdict", "consent_state"):
        if key not in trace:
            errors.append(f"missing_{key}")
    consent = trace.get("consent_state") or {}
    if not (consent.get("opt_in") is True or consent is True or trace.get("consent") is True):
        errors.append("consent_missing")
    san = trace.get("sanitization_report") or {}
    if san.get("passed") is False:
        errors.append("sanitization_failed")
    if san.get("contains_secrets") is True:
        errors.append("secret_bearing_trace")
    verdict = str(trace.get("user_verdict", "")).lower()
    if verdict not in {"accepted", "edited", "rejected", "undone"}:
        errors.append("invalid_verdict")
    if verdict in {"rejected", "undone"}:
        errors.append("not_trainable_verdict")
    if trace.get("stability_result") not in {None, "stable", True} and trace.get("stability_result") != "stable":
        if trace.get("stable") is False or trace.get("stability_result") == "unstable":
            errors.append("unstable_render")
    # secret leakage heuristics
    blob = json.dumps(trace, ensure_ascii=False).lower()
    for needle in ("api_key", "password", "authorization:", "sk-", "-----begin"):
        if needle in blob:
            errors.append("possible_secret_leakage")
            break
    return len(errors) == 0, errors


def trainable_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in traces:
        ok, _ = validate_trace(t)
        if not ok:
            continue
        if t.get("minimum_evidence_met") is False:
            continue
        out.append(t)
    return out


def _session_key(trace: dict[str, Any]) -> str:
    return str(trace.get("workspace_session_id") or trace.get("workspace_id_pseudonym") or trace.get("trace_id"))


def _pair_key(trace: dict[str, Any]) -> str:
    return str(trace.get("render_id") or trace.get("trace_id"))


def deterministic_splits(
    traces: list[dict[str, Any]],
    *,
    seed: str = "render-guardian-v1",
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> dict[str, Any]:
    """Split by session; keep before/after pairs together; record hashes."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    for t in traces:
        by_session.setdefault(_session_key(t), []).append(t)

    sessions = sorted(by_session.keys())
    ranked = sorted(
        sessions,
        key=lambda s: hashlib.sha256(f"{seed}:{s}".encode()).hexdigest(),
    )
    n = len(ranked)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train_s = set(ranked[:n_train])
    val_s = set(ranked[n_train : n_train + n_val])
    test_s = set(ranked[n_train + n_val :])

    def collect(keys: set[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for k in sorted(keys):
            items.extend(sorted(by_session[k], key=lambda x: str(x.get("trace_id"))))
        return items

    splits = {
        "train": collect(train_s),
        "val": collect(val_s),
        "test": collect(test_s),
    }
    # leakage checks
    leaks = detect_split_leakage(splits)
    split_hash = hashlib.sha256(
        json.dumps(
            {k: [t.get("trace_id") for t in v] for k, v in splits.items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "splits": splits,
        "split_hash": split_hash,
        "session_counts": {k: len(v) for k, v in (("train", train_s), ("val", val_s), ("test", test_s))},
        "leakage": leaks,
        "lineage": {"seed": seed, "dataset_size": len(traces)},
    }


def detect_split_leakage(splits: dict[str, list[dict[str, Any]]]) -> list[str]:
    issues: list[str] = []
    seen_sessions: dict[str, str] = {}
    seen_pairs: dict[str, str] = {}
    for split_name, items in splits.items():
        for t in items:
            sk = _session_key(t)
            if sk in seen_sessions and seen_sessions[sk] != split_name:
                issues.append(f"session_leak:{sk}:{seen_sessions[sk]}->{split_name}")
            else:
                seen_sessions[sk] = split_name
            pk = _pair_key(t)
            if pk in seen_pairs and seen_pairs[pk] != split_name:
                issues.append(f"pair_leak:{pk}:{seen_pairs[pk]}->{split_name}")
            else:
                seen_pairs[pk] = split_name
            parent = t.get("lineage_parent") or t.get("teacher_derivative_of")
            if parent:
                for other_name, other_items in splits.items():
                    if other_name == split_name:
                        continue
                    if any(x.get("trace_id") == parent for x in other_items):
                        issues.append(f"derivative_leak:{t.get('trace_id')}->{parent} in {other_name}")
    return issues
