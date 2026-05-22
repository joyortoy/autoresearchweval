from __future__ import annotations

import csv
import json
import math
import os
from typing import Any


RESULTS_HEADER = "commit\tval_bpb\tmemory_gb\tstatus\tdescription\n"


def ensure_dirs(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)


def append_result_row(path: str, commit_hash: str, val_bpb: str, memory_gb: str, status: str, description: str) -> None:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(RESULTS_HEADER)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{commit_hash}\t{val_bpb}\t{memory_gb}\t{status}\t{description}\n")


def best_kept_val_bpb(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    best = math.inf
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row.get("status") != "keep":
                continue
            try:
                best = min(best, float(row.get("val_bpb", "nan")))
            except Exception:
                continue
    return None if math.isinf(best) else f"{best:.6f}"


def save_run_summary(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
