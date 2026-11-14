# Civic Air Quality Briefing Studio

Upload a messy air-quality table; get a cleaned, quality-flagged, fact-cited briefing.

## Setup

    uv sync
    cp .env.example .env   # then fill in values

## Check

    uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest

Full run, deploy and env-var docs are completed in Phase 5.
