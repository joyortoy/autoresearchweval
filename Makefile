PYTHON ?= python3.11

.PHONY: demo test trust-sample lint-shell \
	render-guardian-demo render-guardian-test render-guardian-smoke \
	render-guardian-train render-guardian-smoke-gpu render-guardian-eval \
	render-guardian-autoresearch render-guardian-release render-guardian-env-check

demo:
	$(PYTHON) -m autoresearch.orchestrator --dry-run

test:
	$(PYTHON) -m unittest tests/test_trust_score.py tests/test_orchestrator.py tests/test_render_guardian.py -v

trust-sample:
	$(PYTHON) trust_score.py --policy trust_policy.json --metrics-json examples/trust_metrics.sample.json

lint-shell:
	bash -n run_intent_autoresearch.sh scripts/*.sh sweep_intent_models.sh

render-guardian-demo:
	$(PYTHON) -m autoresearch.orchestrator --dry-run --task joyview_render_guardian --run-name rg_demo

render-guardian-test:
	$(PYTHON) -m unittest tests/test_render_guardian.py -v

render-guardian-smoke:
	RENDER_GUARDIAN_SMOKE=1 $(PYTHON) -m autoresearch.orchestrator --dry-run --task joyview_render_guardian --run-name rg_smoke

render-guardian-train:
	RENDER_GUARDIAN_ENABLE_REAL_TRAIN=1 RENDER_GUARDIAN_SMOKE=0 $(PYTHON) -m autoresearch.orchestrator --task joyview_render_guardian --run-name rg_train

render-guardian-smoke-gpu:
	RENDER_GUARDIAN_ENABLE_REAL_TRAIN=1 RENDER_GUARDIAN_SMOKE=1 $(PYTHON) -m autoresearch.orchestrator --task joyview_render_guardian --run-name rg_smoke_gpu

render-guardian-eval:
	$(PYTHON) -c "from autoresearch.tasks.joyview_render_guardian.evaluate import run_evaluation; import json; print(json.dumps(run_evaluation()['metrics'], indent=2))"

render-guardian-autoresearch:
	$(PYTHON) -m autoresearch.orchestrator --dry-run --task joyview_render_guardian --run-name rg_auto

render-guardian-release:
	$(PYTHON) -m autoresearch.orchestrator --dry-run --task joyview_render_guardian --run-name rg_release

render-guardian-env-check:
	$(PYTHON) -c "from autoresearch.tasks.joyview_render_guardian.env_check import check_environment; import json; print(json.dumps(check_environment(), indent=2))"
