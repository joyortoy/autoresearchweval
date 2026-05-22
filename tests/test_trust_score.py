import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_scorer(payload: dict):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        f.flush()
        out = subprocess.check_output([
            "python3",
            str(ROOT / "trust_score.py"),
            "--policy",
            str(ROOT / "trust_policy.json"),
            "--metrics-json",
            f.name,
        ])
    return json.loads(out)


class TrustScoreTests(unittest.TestCase):
    def test_low_trust_forces_discard(self):
        data = run_scorer({"val_bpb": 1.2, "best_before": 1.0, "safety": 85.0, "data_trust": 20.0, "generalization": 20.0, "human_policy_confidence": 20.0})
        self.assertEqual(data["status"], "discard")

    def test_hard_fail_forces_discard(self):
        data = run_scorer({"val_bpb": 0.8, "best_before": 1.0, "poisoning_risk": "high"})
        self.assertTrue(data["hard_fail"])
        self.assertEqual(data["status"], "discard")

    def test_metric_discard_cannot_be_overridden(self):
        data = run_scorer({
            "val_bpb": 0.8,
            "best_before": 1.0,
            "metric_status": "discard",
            "safety": 99.0,
            "data_trust": 99.0,
            "generalization": 99.0,
            "human_policy_confidence": 99.0,
            "latency_score": 99.0,
            "cost_score": 99.0,
            "reliability_score": 99.0,
        })
        self.assertEqual(data["status"], "discard")

    def test_scorer_failure_fail_closed_contract_doc(self):
        # Contract-level check: trust fallback reason exists in orchestration path.
        text = (ROOT / "autoresearch" / "trust_gate.py").read_text(encoding="utf-8")
        self.assertIn("TRUST_SCORER_UNAVAILABLE", text)
        self.assertIn("discard", text)


if __name__ == "__main__":
    unittest.main()
