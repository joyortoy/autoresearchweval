.PHONY: demo test trust-sample lint-shell

demo:
	python3 -m autoresearch.orchestrator --dry-run

test:
	python3 -m unittest tests/test_trust_score.py tests/test_orchestrator.py -v

trust-sample:
	python3 trust_score.py --policy trust_policy.json --metrics-json examples/trust_metrics.sample.json

lint-shell:
	bash -n run_intent_autoresearch.sh scripts/*.sh sweep_intent_models.sh
