.PHONY: setup lint fmt typecheck test test-integration test-conformance test-all coverage build sync-protos-local

PROTO_SRC_DIR ?= ../multiagentcoordinationprotocol/schemas/proto
PROTO_OUT_DIR = src

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

sync-protos-local:
	@echo "Regenerating Python protobuf code from $(PROTO_SRC_DIR)..."
	python -m grpc_tools.protoc \
		-I$(PROTO_SRC_DIR) \
		--python_out=$(PROTO_OUT_DIR) \
		--grpc_python_out=$(PROTO_OUT_DIR) \
		$(PROTO_SRC_DIR)/macp/v1/envelope.proto \
		$(PROTO_SRC_DIR)/macp/v1/core.proto \
		$(PROTO_SRC_DIR)/macp/modes/decision/v1/decision.proto \
		$(PROTO_SRC_DIR)/macp/modes/proposal/v1/proposal.proto \
		$(PROTO_SRC_DIR)/macp/modes/task/v1/task.proto \
		$(PROTO_SRC_DIR)/macp/modes/handoff/v1/handoff.proto \
		$(PROTO_SRC_DIR)/macp/modes/quorum/v1/quorum.proto
	@echo "Done."
