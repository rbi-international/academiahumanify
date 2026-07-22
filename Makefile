# AcademiaHumanify developer commands.
# Note: on Windows install make (choco install make) or run the underlying
# python -m ... commands directly. Everything below Milestone 5 is pure Python
# with no network or GPU dependency.

.PHONY: setup test lint run up

setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check app tests
	python -m mypy app

# Added in later milestones.
run:
	python -m uvicorn app.api.main:app --reload

up:
	docker compose up
