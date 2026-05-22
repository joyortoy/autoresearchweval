from __future__ import annotations
import json
from trust_score import TrustScorer


def fallback_payload():
    return {
        "trust_score": None,
        "component_scores": {},
        "hard_fail": True,
        "hard_fail_reasons": ["TRUST_SCORER_UNAVAILABLE"],
        "decision": "rollback",
        "status": "discard",
        "reason_codes": ["TRUST_SCORER_UNAVAILABLE"],
        "reason_messages": ["Trust scorer failed or was unavailable; run discarded by fail-closed policy"],
    }

def apply_trust(policy_path:str, trust_log:str, metrics:dict) -> dict:
    try:
        policy=json.load(open(policy_path,encoding='utf-8'))
        result=TrustScorer(policy).score(metrics)
        out={
            "trust_score":result.trust_score,
            "component_scores":result.component_scores,
            "hard_fail":result.hard_fail,
            "hard_fail_reasons":result.hard_fail_reasons,
            "decision":result.decision,
            "status":result.status,
            "reason_codes":result.reason_codes,
        }
    except Exception:
        out=fallback_payload()
    with open(trust_log,'w',encoding='utf-8') as f:
        json.dump(out,f,ensure_ascii=False,indent=2); f.write('\n')
    return out
