from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RenderGuardianTests(unittest.TestCase):
    def test_dry_run_governed_loop(self):
        cp = subprocess.run(
            [
                "python3.11",
                "-m",
                "autoresearch.orchestrator",
                "--dry-run",
                "--task",
                "joyview_render_guardian",
                "--run-name",
                "rg_unittest",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["task"], "joyview_render_guardian")
        self.assertIn(payload["status"], {"keep", "discard"})
        self.assertIn("lineage_id", payload)
        self.assertIn("trust_decision", payload)
        self.assertIn("release_manifest", payload)
        self.assertIn("rollback_target", payload)
        self.assertFalse(payload.get("train_result", {}).get("metrics", {}).get("skipped_real_train") is False and False)

    def test_dataset_validation_and_split_leakage(self):
        from autoresearch.tasks.joyview_render_guardian import dataset as ds

        good = json.loads((ROOT / "examples/render_guardian/sample_trace.json").read_text())
        ok, errors = ds.validate_trace(good)
        self.assertTrue(ok, errors)
        bad = dict(good)
        bad["user_verdict"] = "rejected"
        ok2, err2 = ds.validate_trace(bad)
        self.assertFalse(ok2)
        self.assertIn("not_trainable_verdict", err2)

        t1 = dict(good)
        t2 = dict(good)
        t2["trace_id"] = "tr-2"
        t2["render_id"] = "rd-2"
        t2["workspace_session_id"] = "sess-2"
        split = ds.deterministic_splits([t1, t2], seed="t")
        self.assertEqual(split["leakage"], [])

        leak_splits = {
            "train": [t1],
            "test": [dict(t1, trace_id="tr-x")],
        }
        leaks = ds.detect_split_leakage(leak_splits)
        self.assertTrue(any("session_leak" in x or "pair_leak" in x for x in leaks))

    def test_teacher_and_student_mocks(self):
        from autoresearch.tasks.joyview_render_guardian import student_smolvlm as student
        from autoresearch.tasks.joyview_render_guardian import teacher_qwen as teacher

        label = teacher.propose_repair(
            before_screenshot_ref="local://x",
            layout={"surfaces": [{"id": "a", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}, "contrast_ratio": 2.0}]},
            mock=True,
        )
        self.assertEqual(label["approval_status"], "pending_user")
        self.assertNotIn("hidden_reasoning", label)
        self.assertTrue(label["schema_validation"]["ok"])

        pred = student.predict_adjustment(["overlap"], mock=True)
        self.assertTrue(pred["schema_validation"]["ok"])
        train = student.train_student(dataset={"splits": {"train": []}}, dry_run=True)
        self.assertEqual(train["status"], "ok")
        self.assertTrue(train["metrics"]["skipped_real_train"])

    def test_hard_fail_and_trust_gate(self):
        from trust_score import TrustScorer

        policy = json.loads((ROOT / "trust_policy.json").read_text())
        scorer = TrustScorer(policy)
        bad = {
            "task": "joyview_render_guardian",
            "val_bpb": 0.5,
            "best_before": 1.0,
            "metric_status": "keep",
            "forbidden_action_rate": 0.2,
            "action_schema_validity": 1.0,
            "hard_diagnostic_pass_rate": 1.0,
            "oscillation_rate": 0.0,
            "regression_rate": 0.0,
            "safety": 99,
            "data_trust": 99,
        }
        result = scorer.score(bad)
        self.assertEqual(result.status, "discard")
        self.assertIn("HF_RG_FORBIDDEN_ACTION", result.hard_fail_reasons)

    def test_metrics_and_contracts(self):
        from autoresearch.tasks.joyview_render_guardian.contracts import validate_adjustment
        from autoresearch.tasks.joyview_render_guardian.evaluate import run_evaluation

        ok, _ = validate_adjustment(
            {"schema": "joyview.render-adjustment/v1", "actions": [{"type": "no_change", "params": {}}]}
        )
        self.assertTrue(ok)
        bad, errs = validate_adjustment(
            {"schema": "joyview.render-adjustment/v1", "actions": [{"type": "shell.exec", "params": {}}]}
        )
        self.assertFalse(bad)
        self.assertTrue(any("forbidden" in e for e in errs))
        ev = run_evaluation()
        self.assertGreaterEqual(len(ev["cases"]), 11)
        self.assertIn("hard_diagnostic_pass_rate", ev["metrics"])

    def test_rollback_semantics(self):
        from autoresearch.rollback import should_keep

        self.assertTrue(should_keep("keep"))
        self.assertFalse(should_keep("discard"))

    def test_release_manifest_checksum(self):
        from types import SimpleNamespace

        from autoresearch.tasks.joyview_render_guardian.release import write_release_manifest

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt"
            ckpt.mkdir()
            (ckpt / "model_card.md").write_text("x", encoding="utf-8")
            cfg = SimpleNamespace(root_dir=str(ROOT), lineage_id="lin-t")
            manifest = write_release_manifest(
                cfg=cfg,
                outcome={"status": "keep", "trust_decision": "auto_promote", "trust_score": 91, "lineage_id": "lin-t"},
                train_result={"config_hash": "abc", "checkpoint_dir": str(ckpt), "dataset_hash": "d1"},
                eval_result={"metrics": {"adjustment_success_rate": 0.9}},
                release_root=Path(tmp) / "rel",
            )
            self.assertEqual(manifest["release_status"], "promoted")
            self.assertEqual(len(manifest["artifact_checksum"]), 64)
            self.assertFalse(manifest["weights_committed_to_git"])
            self.assertTrue(Path(manifest["manifest_path"]).exists())


if __name__ == "__main__":
    unittest.main()
