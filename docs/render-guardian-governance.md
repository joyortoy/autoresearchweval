# Render Guardian governance

## Non-negotiables

- Reuse `trust_score.py` + `trust_policy.json`
- Fail closed on scorer errors
- `metric_status=discard` cannot be overridden
- Teacher labels require user accept/edit + diagnostic improvement + stability + sanitization
- No auto-promotion from training loss alone

## Additive hard fails

`task_profiles.joyview_render_guardian` adds Render Guardian hard fails without weakening global hard_fail.

Examples: forbidden actions, schema invalidity, sensitive content, oscillation, split leakage, unauthorized traces, memory budget, incumbent regression.

## User authority

Final approved adjustment is the training label. Rejected/undone/temporary experiments are excluded.
