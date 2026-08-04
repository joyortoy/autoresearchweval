from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .contracts import ALLOWED_ACTIONS, PROMPT_VERSION, SCHEMA_ADJUSTMENT, output_hash, validate_adjustment
from .diagnostics import run_diagnostics


DEFAULT_TEACHER = os.getenv("RENDER_GUARDIAN_TEACHER_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
DEFAULT_REVISION = os.getenv("RENDER_GUARDIAN_TEACHER_REVISION", "main")


def propose_repair(
    *,
    before_screenshot_ref: str,
    layout: dict[str, Any],
    diagnostics: list[dict[str, Any]] | None = None,
    prior_patterns: list[dict[str, Any]] | None = None,
    mock: bool = True,
) -> dict[str, Any]:
    """Qwen-VL teacher adapter. Mock by default; real inference is optional/env-gated."""
    findings = diagnostics if diagnostics is not None else run_diagnostics(layout)
    if mock or os.getenv("RENDER_GUARDIAN_TEACHER_MOCK", "1") == "1":
        adjustment = _mock_adjustment(findings)
    else:
        # Real teacher path is intentionally gated; fail closed to mock-structured output
        # unless a caller injects RENDER_GUARDIAN_TEACHER_IMPL.
        impl = os.getenv("RENDER_GUARDIAN_TEACHER_IMPL", "")
        if not impl:
            adjustment = _mock_adjustment(findings)
        else:
            raise RuntimeError("external teacher impl hook not configured in this environment")

    ok, errors = validate_adjustment(adjustment)
    record = {
        "schema": "joyview.teacher-label/v1",
        "teacher_model_id": DEFAULT_TEACHER,
        "revision": DEFAULT_REVISION,
        "prompt_version": PROMPT_VERSION,
        "generation_parameters": {
            "temperature": 0.0,
            "max_tokens": 512,
            "mock": True if mock or os.getenv("RENDER_GUARDIAN_TEACHER_MOCK", "1") == "1" else False,
        },
        "inputs": {
            "before_screenshot_ref": before_screenshot_ref,
            "diagnostic_codes": [f.get("code") for f in findings],
            "allowed_actions": sorted(ALLOWED_ACTIONS),
            "prior_pattern_count": len(prior_patterns or []),
        },
        "identified_issues": [f.get("code") for f in findings],
        "proposed_adjustment": adjustment,
        "confidence": 0.55 if findings else 0.9,
        "escalation_recommendation": any(f.get("code") == "unstable_oscillation" for f in findings)
        or layout.get("ambiguous") is True,
        "output_hash": output_hash(adjustment),
        "schema_validation": {"ok": ok, "errors": errors},
        "user_correction_delta": None,
        "approval_status": "pending_user",
        # intentionally no hidden_reasoning / chain-of-thought field
    }
    return record


def _mock_adjustment(findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not findings:
        return {
            "schema": SCHEMA_ADJUSTMENT,
            "actions": [{"type": "no_change", "params": {}}],
            "rationale_codes": ["no_issue"],
        }
    codes = {f.get("code") for f in findings}
    if "overlap" in codes:
        actions = [{"type": "surface.move", "params": {"surface_id": "s1", "dx": 16, "dy": 0}}]
    elif "contrast_failure" in codes:
        actions = [{"type": "theme.adjust_contrast", "params": {"delta": 0.15}}]
    elif "hidden_critical_control" in codes:
        actions = [{"type": "widget.show", "params": {"widget_id": "primary"}}]
    elif "distracting_wallpaper" in codes or layout_has_wallpaper_issue(codes):
        actions = [{"type": "wallpaper.adjust_opacity", "params": {"opacity": 0.2}}]
    else:
        actions = [{"type": "layout.set_spacing", "params": {"spacing": "comfortable"}}]
    if any(f.get("severity") == "critical" and f.get("code") == "unstable_oscillation" for f in findings):
        actions = [{"type": "escalate_to_joyclaw", "params": {"reason": "oscillation"}}]
    return {
        "schema": SCHEMA_ADJUSTMENT,
        "actions": actions,
        "rationale_codes": sorted(c for c in codes if c),
    }


def layout_has_wallpaper_issue(codes: set[Any]) -> bool:
    return "distracting_wallpaper" in codes


def apply_user_verdict(teacher_record: dict[str, Any], *, verdict: str, final_adjustment: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(teacher_record)
    out["approval_status"] = verdict
    if final_adjustment is not None and final_adjustment != teacher_record.get("proposed_adjustment"):
        out["user_correction_delta"] = {
            "teacher_hash": teacher_record.get("output_hash"),
            "final_hash": output_hash(final_adjustment),
        }
    return out


def is_trainable_teacher_label(
    teacher_record: dict[str, Any],
    *,
    user_verdict: str,
    diagnostics_improved: bool,
    stable: bool,
    sanitization_ok: bool,
    no_oscillation: bool,
) -> bool:
    schema_ok = bool((teacher_record.get("schema_validation") or {}).get("ok"))
    return (
        schema_ok
        and user_verdict in {"accepted", "edited"}
        and diagnostics_improved
        and stable
        and sanitization_ok
        and no_oscillation
    )
