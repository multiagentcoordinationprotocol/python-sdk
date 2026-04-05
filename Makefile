.PHONY: setup lint fmt typecheck test test-integration test-conformance test-all coverage build sync-protos sync-protos-local check-protos gen-protos

SPEC_PROTO_DIR := ../multiagentcoordinationprotocol/schemas/proto
PROTO_OUT_DIR := src
PROTO_FILES := macp/v1/envelope.proto macp/v1/core.proto macp/modes/decision/v1/decision.proto macp/modes/proposal/v1/proposal.proto macp/modes/task/v1/task.proto macp/modes/handoff/v1/handoff.proto macp/modes/quorum/v1/quorum.proto

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

## Regenerate Python protobuf/gRPC code from the proto/ directory
gen-protos:
	@echo "Regenerating Python protobuf code from proto/..."
	python -m grpc_tools.protoc \
		-Iproto \
		--python_out=$(PROTO_OUT_DIR) \
		--grpc_python_out=$(PROTO_OUT_DIR) \
		$(addprefix proto/,$(PROTO_FILES))
	@echo "Done."

## Pull latest proto files from BSR, then regenerate Python code
sync-protos:
	buf export buf.build/multiagentcoordinationprotocol/macp -o proto
	@echo "Proto files updated from BSR."
	$(MAKE) gen-protos
	@echo "Done. Run 'git diff proto/ src/macp/' to review changes."

## Sync from local sibling checkout (for development before BSR publish)
sync-protos-local:
	@if [ ! -d "$(SPEC_PROTO_DIR)" ]; then \
		echo "Error: Spec repo not found at $(SPEC_PROTO_DIR)"; \
		echo "Use 'make sync-protos' to sync from BSR instead."; \
		exit 1; \
	fi
	@for f in $(PROTO_FILES); do \
		mkdir -p proto/$$(dirname $$f); \
		cp "$(SPEC_PROTO_DIR)/$$f" "proto/$$f"; \
		echo "  Copied $$f"; \
	done
	@echo "Proto files updated from local checkout."
	$(MAKE) gen-protos
	@echo "Done. Run 'git diff proto/ src/macp/' to review changes."

## Check if local protos match BSR
check-protos:
	@TMPDIR=$$(mktemp -d); \
	buf export buf.build/multiagentcoordinationprotocol/macp -o "$$TMPDIR"; \
	DRIFT=0; \
	for f in $(PROTO_FILES); do \
		if ! diff -q "$$TMPDIR/$$f" "proto/$$f" > /dev/null 2>&1; then \
			echo "DRIFT: $$f"; \
			DRIFT=1; \
		fi; \
	done; \
	rm -rf "$$TMPDIR"; \
	if [ "$$DRIFT" -eq 0 ]; then \
		echo "All proto files match BSR."; \
	else \
		echo "Run 'make sync-protos' to update."; \
		exit 1; \
	fi
