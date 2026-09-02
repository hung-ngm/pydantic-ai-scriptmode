.DEFAULT_GOAL := all

.PHONY: .uv install format lint typecheck test testcov all

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

all: format lint typecheck test
