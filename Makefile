.DEFAULT_GOAL := all

.PHONY: .uv install format lint typecheck test testcov durability all

.uv:
	@uv --version || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

install: .uv
	uv sync --group lint

format:
	uv run ruff format
	uv run ruff check --fix --fix-only

lint:
	uv run ruff format --check
	uv run ruff check

typecheck:
	uv run pyright

test:
	uv run pytest

testcov:
	uv run coverage run -m pytest
	uv run coverage report

# The durability tests need the `durability` group; they skip when it is not installed.
durability:
	uv run --group durability pytest tests/test_temporal.py tests/test_dbos.py

all: format lint typecheck test
