from __future__ import annotations
import subprocess, re

def run_training(train_log: str) -> tuple[int, str, str, str]:
    cp = subprocess.run(["uv","run","train.py"], text=True, capture_output=True)
    with open(train_log,'w',encoding='utf-8') as f:
        f.write(cp.stdout)
        if cp.stderr:
            f.write("\n"+cp.stderr)
    val = _extract(cp.stdout, 'val_bpb')
    peak = _extract(cp.stdout, 'peak_vram_mb')
    return cp.returncode, val, peak, cp.stdout

def _extract(text,key):
    m=re.search(rf"^{re.escape(key)}:\s+([0-9.]+)$", text, re.MULTILINE)
    return m.group(1) if m else ''
