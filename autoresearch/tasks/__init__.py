from __future__ import annotations

from typing import Any

from .base import TaskAdapter


def get_task(name: str) -> TaskAdapter:
    key = (name or "").strip().lower()
    if key in {"joyview_render_guardian", "render_guardian", "render-guardian"}:
        from .joyview_render_guardian import JoyViewRenderGuardianAdapter

        return JoyViewRenderGuardianAdapter()
    raise KeyError(f"unknown task profile: {name!r}")


def list_tasks() -> list[str]:
    return ["joyview_render_guardian"]


__all__ = ["TaskAdapter", "get_task", "list_tasks"]
