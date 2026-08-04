from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .student_smolvlm import env_capable_for_train


def check_environment(*, min_disk_gb: float = 10.0, min_vram_gb: float = 8.0) -> dict[str, Any]:
    torch_info = env_capable_for_train()
    disk = shutil.disk_usage(Path.cwd())
    disk_free_gb = disk.free / (1024**3)
    ok = True
    reasons: list[str] = []
    if disk_free_gb < min_disk_gb:
        ok = False
        reasons.append(f"disk_low:{disk_free_gb:.1f}GB")
    if not torch_info.get("torch"):
        reasons.append("torch_missing")
    if not torch_info.get("cuda"):
        reasons.append("cuda_missing_or_unavailable")
    vram = float(torch_info.get("vram_gb") or 0)
    if torch_info.get("cuda") and vram and vram < min_vram_gb:
        reasons.append(f"vram_low:{vram}GB")
    return {
        "ok_for_smoke": True,  # smoke/dry-run always allowed
        "ok_for_full_train": bool(torch_info.get("cuda")) and disk_free_gb >= min_disk_gb and not any(
            r.startswith("vram_low") for r in reasons
        ),
        "disk_free_gb": round(disk_free_gb, 2),
        "torch": torch_info,
        "reasons": reasons,
        "timeout_s": int(os.getenv("RENDER_GUARDIAN_TIMEOUT_S", "7200")),
        "notes": "RTX 5090 host expected for full train; this check is advisory and fail-closed for real train.",
    }


def cleanup_candidates(root: str | Path = "releases/render_guardian/candidates") -> dict[str, Any]:
    p = Path(root)
    removed = 0
    if p.exists():
        for child in p.iterdir():
            if child.is_dir() and child.name.startswith("mock-"):
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
    return {"removed_mock_dirs": removed}
