# Initial Findings (Sanitized Sample)

## Test window summary

This document summarizes a small public-safe sample from a bounded complex-intent autoresearch loop. The sample is sanitized metadata only (metrics + keep/discard outcomes), without private infrastructure details, identities, screenshots, or local-machine artifacts.

**Required interpretation statement:**

Initial testing metadata shows that the complex-intent loop produced both keep and discard decisions across bounded iterations. These samples demonstrate that the loop is operational and metric-driven, but they do not validate alignment, attention telemetry, or causal safety claims.

## Sanitized run table

| source | loop | iteration | status | experiment | planner | loss | accuracy | macro_f1 | vram_gb | trend | note |
|---|---|---:|---|---|---|---:|---:|---:|---:|---|---|
| complex_intent_sanitized | complex_intent | 1 | keep | best-lr-down | planner_v1 | 0.842 | 0.781 | 0.742 | 21.4 | improving | baseline keep decision |
| complex_intent_sanitized | complex_intent | 2 | discard | best-lr-down | planner_v1 | 0.911 | 0.744 | 0.701 | 21.6 | weakening | macro_f1 drop triggered discard |
| complex_intent_sanitized | complex_intent | 3 | keep | best-lr-up | planner_v2 | 0.803 | 0.796 | 0.758 | 22.1 | improving | recovered on lr-up branch |
| complex_intent_sanitized | complex_intent | 4 | discard | best-lr-up | planner_v2 | 0.956 | 0.721 | 0.673 | 22.0 | weakening | accuracy and macro_f1 regressed |
| complex_intent_sanitized | complex_intent | 5 | keep | best-lr-down | planner_v2 | 0.788 | 0.804 | 0.769 | 22.3 | improving | new local best in sample window |
| complex_intent_sanitized | complex_intent | 6 | discard | best-lr-down | planner_v2 | 0.928 | 0.736 | 0.689 | 22.2 | weakening | loss spike with lower macro_f1 |

## What this evidence shows

- The loop executes bounded iterations and records structured run metadata.
- The loop can emit both `keep` and `discard` decisions in one test window.
- Kept runs appear in both `best-lr-down` and `best-lr-up` branches.
- Discarded runs appear when metrics weaken.
- `macro_f1` varies materially across iterations.

These observed patterns support the need for calibration and longitudinal drift tracking.

## What this evidence does **not** show

- It does not prove alignment.
- It does not prove internal attention/representation safety.
- It does not establish causal guarantees from telemetry signals.
- It does not demonstrate production robustness across domains or adversarial settings.

## Limitations

- Sample size is small and intentionally sanitized.
- Metrics are illustrative and not a full benchmark suite.
- No claim is made that this sample alone validates trust policy quality.

## Next calibration steps

1. Expand sanitized test windows to include more seeds and planner variants.
2. Compare keep/discard outcomes against held-out evaluation slices.
3. Track drift-like metrics longitudinally across lineage to detect gradual degradation.
4. Add adversarial and ambiguous prompt calibration batches before widening promotion scope.
