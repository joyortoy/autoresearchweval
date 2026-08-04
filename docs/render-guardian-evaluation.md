# Render Guardian evaluation

Harness: `autoresearch/tasks/joyview_render_guardian/evaluate.py`

## Layers

1. Deterministic diagnostics (hard layer)
2. Structured action generation validity
3. Repair success / second-render verification
4. no_change + escalation correctness
5. Golden synthetic defects + approved sanitized traces

## Golden set

Under `autoresearch/tasks/joyview_render_guardian/golden/` — clipped text, overlap, reading order, density, contrast, wallpaper, hidden primary, wasted space, responsive failure, no issue, ambiguous escalation.
