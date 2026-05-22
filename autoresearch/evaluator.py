def metric_status(val_bpb: str, best_before: str | None) -> str:
    if not best_before:
        return 'keep'
    try:
        return 'keep' if float(val_bpb) < float(best_before) else 'discard'
    except Exception:
        return 'discard'
