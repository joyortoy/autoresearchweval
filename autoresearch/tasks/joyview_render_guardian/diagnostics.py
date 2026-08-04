from __future__ import annotations

from typing import Any


Finding = dict[str, Any]


def _rect(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    b = item.get("bounds") or {}
    try:
        x, y = float(b["x"]), float(b["y"])
        w, h = float(b["width"]), float(b["height"])
        return x, y, x + w, y + h
    except Exception:
        return None


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def run_diagnostics(layout: dict[str, Any], *, viewport: dict[str, Any] | None = None) -> list[Finding]:
    """Deterministic hard-evaluation layer from layout metadata (no model)."""
    findings: list[Finding] = []
    surfaces = list(layout.get("surfaces") or [])
    viewport = viewport or layout.get("viewport") or {"width": 1280, "height": 800}
    vw = float(viewport.get("width", 1280))
    vh = float(viewport.get("height", 800))

    rects: list[tuple[str, tuple[float, float, float, float]]] = []
    owners: dict[str, str] = {}
    for surf in surfaces:
        sid = str(surf.get("id", ""))
        owner = str(surf.get("owner", ""))
        if owner:
            if owner in owners and owners[owner] != sid:
                findings.append(
                    {"code": "duplicate_surface_ownership", "severity": "critical", "surface_id": sid}
                )
            owners[owner] = sid
        r = _rect(surf)
        if r is None:
            continue
        rects.append((sid, r))
        if r[0] >= vw or r[1] >= vh or r[2] <= 0 or r[3] <= 0:
            findings.append({"code": "off_screen_surface", "severity": "critical", "surface_id": sid})
        if r[0] < 0 or r[1] < 0 or r[2] > vw or r[3] > vh:
            findings.append({"code": "viewport_clipping", "severity": "critical", "surface_id": sid})
        z = surf.get("z_index")
        if z is not None and int(z) < 0:
            findings.append({"code": "invalid_z_order", "severity": "high", "surface_id": sid})
        font = float(surf.get("font_size_px") or 0)
        if font and font < 11:
            findings.append({"code": "unreadable_font_size", "severity": "high", "surface_id": sid})
        if surf.get("text_overflow"):
            findings.append({"code": "text_overflow", "severity": "high", "surface_id": sid})
        tw = float(surf.get("touch_width_px") or 0)
        th = float(surf.get("touch_height_px") or 0)
        if (tw and tw < 44) or (th and th < 44):
            findings.append({"code": "touch_target_violation", "severity": "high", "surface_id": sid})
        contrast = float(surf.get("contrast_ratio") or 99)
        if contrast < 4.5:
            findings.append({"code": "contrast_failure", "severity": "critical", "surface_id": sid})
        if surf.get("critical") and surf.get("hidden"):
            findings.append({"code": "hidden_critical_control", "severity": "critical", "surface_id": sid})
        nest = int(surf.get("nested_scroll_depth") or 0)
        if nest > 2:
            findings.append({"code": "excessive_nested_scrolling", "severity": "medium", "surface_id": sid})
        if surf.get("invalid_grid"):
            findings.append({"code": "invalid_grid_constraints", "severity": "high", "surface_id": sid})

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _overlap(rects[i][1], rects[j][1]):
                findings.append(
                    {
                        "code": "overlap",
                        "severity": "critical",
                        "surface_ids": [rects[i][0], rects[j][0]],
                    }
                )

    order = [str(s.get("id")) for s in surfaces if s.get("reading_order") is not None]
    orders = [int(s.get("reading_order")) for s in surfaces if s.get("reading_order") is not None]
    if orders and orders != sorted(orders):
        findings.append({"code": "broken_reading_order", "severity": "high", "surface_ids": order})

    if layout.get("unused_high_priority_space"):
        findings.append({"code": "unused_high_priority_space", "severity": "medium"})

    history = list(layout.get("adjustment_history") or [])
    if len(history) >= 4:
        a, b = history[-4:-2], history[-2:]
        if a == b:
            findings.append({"code": "unstable_oscillation", "severity": "critical"})

    return findings


def critical_worsened(before: list[Finding], after: list[Finding]) -> bool:
    crit = {"overlap", "viewport_clipping", "hidden_critical_control", "unstable_oscillation"}
    b = {f["code"] for f in before if f.get("severity") == "critical" or f.get("code") in crit}
    a = {f["code"] for f in after if f.get("severity") == "critical" or f.get("code") in crit}
    return len(a - b) > 0 or (len([f for f in after if f.get("code") in crit]) > len([f for f in before if f.get("code") in crit]))


def improvement_score(before: list[Finding], after: list[Finding]) -> float:
    bw = sum(3 if f.get("severity") == "critical" else 2 if f.get("severity") == "high" else 1 for f in before)
    aw = sum(3 if f.get("severity") == "critical" else 2 if f.get("severity") == "high" else 1 for f in after)
    if bw == 0 and aw == 0:
        return 1.0
    if bw == 0:
        return 0.0 if aw > 0 else 1.0
    return max(0.0, min(1.0, (bw - aw) / bw))
