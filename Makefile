.PHONY: setup lint fmt typecheck test test-integration test-conformance test-all coverage build sync-fixtures dev-link-protos

SPEC_CONFORMANCE_DIR := ../multiagentcoordinationprotocol/schemas/conformance

setup:
	pip install -e ".[dev,docs]"

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/

typecheck:
	mypy src/macp_sdk/

test:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v -m integration

test-conformance:
	pytest tests/conformance/ -v -m conformance

test-all: lint typecheck test test-integration test-conformance

coverage:
	pytest --cov=macp_sdk --cov-report=html --cov-report=term tests/unit/

build:
	python -m build

## Sync conformance fixtures from canonical source
sync-fixtures:
	@if [ ! -d "$(SPEC_CONFORMANCE_DIR)" ]; then \
		echo "Error: Spec repo not found at $(SPEC_CONFORMANCE_DIR)"; \
		exit 1; \
	fi
	@for f in $(SPEC_CONFORMANCE_DIR)/*.json; do \
		cp "$$f" tests/conformance/; \
		echo "  Copied $$(basename $$f)"; \
	done
	@echo "Done. Run 'git diff tests/conformance/' to review changes."

## Install local proto package for development (test proto changes before publishing)
dev-link-protos:
	pip install -e ../multiagentcoordinationprotocol/packages/proto-python
	@echo "Installed local macp-proto. Changes to proto-python/src/macp/ are reflected immediately."
