#!/usr/bin/env python3
import json, sys

def payload():
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

def main():
    with open(sys.argv[1],"w",encoding="utf-8") as f:
        json.dump(payload(), f, ensure_ascii=False, indent=2); f.write("\n")

if __name__ == '__main__':
    main()
