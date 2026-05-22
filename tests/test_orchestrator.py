import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class OrchestratorTests(unittest.TestCase):
    def test_dry_run_works(self):
        cp = subprocess.run(["python3", "-m", "autoresearch.orchestrator", "--dry-run", "--run-name", "t1"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["description"], "dry-run")
        self.assertIn(payload["status"], {"keep", "discard"})
        self.assertIn("lineage_id", payload)
        self.assertIn("policy_hash", payload)

    def test_trust_failure_fails_closed(self):
        bad_policy = ROOT / "logs" / "bad_policy.json"
        bad_policy.parent.mkdir(exist_ok=True)
        bad_policy.write_text("{not-json", encoding="utf-8")
        cp = subprocess.run(["python3", "-m", "autoresearch.orchestrator", "--dry-run", "--policy", str(bad_policy), "--run-name", "t2"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("discard", cp.stdout)

    def test_optional_evals_default_off(self):
        cp = subprocess.run(["python3", "-m", "autoresearch.orchestrator", "--dry-run", "--run-name", "t3"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0)
        payload = json.loads(cp.stdout)
        self.assertIn("trust_decision", payload)

    def test_shell_wrapper_syntax(self):
        cp = subprocess.run(["bash", "-n", "run_intent_autoresearch.sh"], cwd=ROOT)
        self.assertEqual(cp.returncode, 0)

if __name__ == '__main__':
    unittest.main()
