# Civic Air Quality Briefing Studio

Upload a messy air-quality table; get a cleaned, quality-flagged, fact-cited briefing. Code
computes every number; the AI only writes the explanation, and a verifier checks each sentence
against the computed facts. Product rules: `CLAUDE.md`. Backend scope and API contract:
`BACKEND_PLAN.md`.

## Setup

    uv sync
    cp .env.example .env   # then fill in values

## Run

    uv run uvicorn aqstudio.web.main:app

Open http://localhost:8000. The web app (`frontend/`, plain HTML/CSS/JS, no build step) is served
at `/` and talks to the JSON API under `/api` (OpenAPI at `/openapi.json`).

## Environment variables

| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | AI provider key (Sarvam-hosted models). Never commit it. |
| `SARVAM_MODEL` | Model id, default `deepseekv4.1-flash-1017`. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Optional alternative provider. |
| `LLM_PROVIDER` | `auto` (Anthropic if its key is set, else Sarvam), `anthropic` or `sarvam`. |
| `SESSION_SECRET` | Signs the browser-session cookie. |
| `COOKIE_SECURE` | `true` when served over HTTPS. |
| `DATABASE_PATH` | SQLite file (default `aqstudio.sqlite3`). |

Without an AI key the app reports that the AI service is not configured; it never falls back to
canned text.

## Check

    uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest

## Compare models

    uv run python scripts/eval_models.py

Runs several models on one synthetic messy dataset and reports speed and how many claims the
verifier rejects, with reasons.

## Deploy

`render.yaml` describes the Render web service. Set `SARVAM_API_KEY` in the dashboard.
Render's free tier has no persistent disk, so stored briefs are lost on restart.
