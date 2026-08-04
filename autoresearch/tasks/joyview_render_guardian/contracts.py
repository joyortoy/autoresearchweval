from __future__ import annotations

import hashlib
import json
from typing import Any

ALLOWED_ACTIONS = frozenset(
    {
        "surface.move",
        "surface.resize",
        "surface.reorder",
        "surface.attach",
        "surface.detach",
        "layout.set_columns",
        "layout.set_density",
        "layout.set_spacing",
        "layout.set_priority",
        "widget.show",
        "widget.hide",
        "widget.collapse",
        "widget.expand",
        "theme.adjust_contrast",
        "theme.adjust_typography",
        "wallpaper.adjust_opacity",
        "wallpaper.disable",
        "scroll_region.adjust",
        "no_change",
        "escalate_to_joyclaw",
    }
)

FORBIDDEN_ACTION_PREFIXES = (
    "shell.",
    "http.",
    "network.",
    "secret.",
    "code.",
    "payment.",
    "permission.",
    "install.",
    "joylegal.",
    "data.mutate",
    "business.",
)

SCHEMA_ADJUSTMENT = "joyview.render-adjustment/v1"
SCHEMA_TRACE = "joyview.render-training-trace/v1"
SCHEMA_EVAL = "joyview.render-evaluation/v1"
SCHEMA_MANIFEST = "joyview.model-release-manifest/v1"
PROMPT_VERSION = "rg-teacher-v1"


def action_allowed(action: str) -> bool:
    return action in ALLOWED_ACTIONS


def validate_adjustment(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return False, ["adjustment must be object"]
    if payload.get("schema") != SCHEMA_ADJUSTMENT:
        errors.append("invalid schema id")
    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) == 0:
        errors.append("actions must be non-empty list")
        return False, errors
    if len(actions) > 8:
        errors.append("too many actions in one pass")
    for item in actions:
        if not isinstance(item, dict):
            errors.append("action entry must be object")
            continue
        name = str(item.get("type", ""))
        if not action_allowed(name):
            errors.append(f"forbidden_or_unknown_action:{name}")
        if any(name.startswith(p) for p in FORBIDDEN_ACTION_PREFIXES):
            errors.append(f"forbidden_prefix:{name}")
    return len(errors) == 0, errors


def output_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
