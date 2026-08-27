# be-stats
#
# `test` is the ordinary suite: pure Python, one dependency, seconds.
# `validate` is the external cross-check: Docker, R, PowerTOST, minutes.
#
# They are separate targets because they answer different questions. `test`
# asks whether the code does what the documentation says. `validate` asks
# whether an independent implementation agrees with the numbers.

PYTHON ?= python
DOCKER ?= docker
IMAGE  ?= be-stats-validation

.PHONY: help test validate validate-python validate-image clean

help:
	@echo "test             run the ordinary suite (no R, no Docker)"
	@echo "validate         build the validation image and run the cross-check"
	@echo "validate-python  run the harness locally; comparisons report SKIPPED"
	@echo "                 unless Rscript is on PATH"
	@echo "validate-image   build the validation image only"

test:
	$(PYTHON) -m pytest

validate-image:
	$(DOCKER) build -t $(IMAGE) validation/external

# The one command. Mounts the repository root so the container sees both the
# package source and the case files.
validate: validate-image
	$(DOCKER) run --rm -v "$(CURDIR)/..:/work" $(IMAGE)

# Without Docker or R. The Python side of every case still runs, and every
# comparison reports SKIPPED - which is the point: a missing environment must
# never look like agreement.
validate-python:
	PYTHONPATH=src $(PYTHON) validation/external/harness.py \
		--json-out validation/external/report.json \
		--text-out validation/external/report.txt

clean:
	rm -f validation/external/report.json \
	      validation/external/report.txt \
	      validation/external/powertost_results.json
