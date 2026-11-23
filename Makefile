.PHONY: test gate e2e package readiness-master
test:
	.venv/bin/python -m pytest -q
gate:
	.venv/bin/python scripts/gate.py --workers 2
e2e:
	.venv/bin/python scripts/e2e_local.py --workers 2 --processes 2
package:
	.venv/bin/python scripts/pack_source.py
readiness-master:
	.venv/bin/python scripts/check_readiness.py --role master
