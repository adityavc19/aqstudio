> **Precedence:** `BACKEND_PLAN.md` is the source of truth for backend scope, schemas and the API contract. Where it conflicts with this file (e.g. JSON API + static frontend instead of Jinja2/HTMX), follow `BACKEND_PLAN.md`.

# Civic Air Quality Briefing Studio

Project brief and working rules for Claude Code. Read this fully before writing code. Follow it over defaults.

## 1. What we are building

A web app for the Google for Developers **PromptWars** warm-up challenge, "Civic Air Quality Briefing Studio".

A user pastes or uploads an air-quality data table (often messy). The app:

1. Parses and cleans it, recording every change in a ledger.
2. Flags data-quality problems (gaps, stuck sensors, ceilings, unit mismatches, implausible values).
3. Computes facts deterministically (coverage-aware stats, CPCB AQI, hotspots, trends).
4. Uses an LLM (Claude) to interpret those facts in plain language, with every claim citing a fact ID.
5. Verifies the LLM output in code (citations exist, quoted numbers match).
6. Recommends prioritized local actions for the persona asking (ward officer, housing society, school).
7. Compares the new brief with the previous one to show what changed (coverage-aware).
8. Produces an internal briefing note and a citizen advisory in multiple languages and reading levels, with extra care for children, older adults and sensitive groups.
9. Shows stations on a map, with a table alternative.

The organizers give no dataset. Users bring their own data.

## 2. How we are judged (drives every decision)

Hands-on functional evaluation of the deployed app, scored on six parameters (all count):

| Parameter | Weight | What it means for us |
|---|---|---|
| Code quality | High | Clean, readable, well-structured, typed, consistent |
| Problem statement alignment | High | Every item in section 1 is visibly working |
| Security | Medium | No common vulnerabilities, no leaked secrets |
| Efficiency | Medium | Sensible time and memory use, small LLM payloads |
| Testing | Low | Tests exist, run, and are meaningful |
| Accessibility | Low | Usable by diverse users; keyboard, contrast, semantics |

Low-weight items break ties, so do not skip them, but never trade High items for them.

### Disqualification rules (hard constraints)

- **No static or hardcoded pages** that show an outcome without real logic producing it.
- **No mock or fake data presented as real output.** A "Load sample data" button is allowed only if it is clearly labelled as sample data and runs through the real pipeline, including the real LLM call.
- **No canned or hallucinated AI responses.** Every LLM-derived output must come from a real API call. If the call fails, show an honest error. Never fall back to a pre-written brief.
- **No false positives.** A feature that appears to work in a demo but fails on genuine testing is worse than no feature. Cut it rather than fake it.
- **No login.** The app has no authentication, so evaluators need no credentials.
- Every feature shown in the demo must work end-to-end on the deployed URL.

When in doubt: build fewer features that genuinely work.

## 3. Stack and conventions

- **Python 3.12**, **FastAPI**, **pydantic v2**, **pandas**, **pytest**, **ruff**, **mypy (strict on `src/`)**.
- Frontend: server-rendered **Jinja2** templates, **HTMX** for interactions, **Leaflet** for the map. No JS build step, no SPA framework.
- Storage: **SQLite** (via the stdlib `sqlite3` or SQLModel) for saved briefs.
- LLM: **Anthropic Python SDK**. Model name comes from the env var `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`). Use tool use / structured output so responses are schema-validated.
- Package management: `uv` or `pip` with a pinned `requirements.txt` / `pyproject.toml`. Pin versions.

Code conventions:

- Small pure functions. Each pipeline stage is a function that takes typed input and returns typed output.
- Pydantic models are the contract between stages. No passing raw dicts or DataFrames across module boundaries except inside `clean/` and `facts/`.
- No global mutable state. Pass dependencies in (the LLM client is injected).
- Public functions have type hints and a one-line docstring. Comments explain why, not what.
- No dead code, no commented-out code, no TODOs left in submitted code.
- Every constant with domain meaning (AQI breakpoints, plausibility ranges, thresholds) lives in one config module with a source comment.

## 4. Repository layout

```
.
├── CLAUDE.md
├── README.md                 # setup, run, test, deploy, env vars
├── pyproject.toml
├── .env.example              # no real secrets, ever
├── src/aqstudio/
│   ├── config.py             # settings, thresholds, breakpoints
│   ├── schemas.py            # all pydantic models
│   ├── ingest/               # format sniffing + parsers (long, wide, pasted, xlsx, pdf-text)
│   ├── clean/                # normalization + cleaning ledger
│   ├── quality/              # data-quality detectors and per-station reliability
│   ├── facts/                # deterministic stats, AQI, hotspots, trends, fact IDs
│   ├── llm/                  # Claude client wrapper, prompts, schema-constrained calls
│   ├── verify/               # citation + number verification of LLM output
│   ├── actions/              # persona-specific action generation
│   ├── compare/              # brief-to-brief diff
│   ├── advisory/             # citizen advisory: languages, reading levels, sensitive groups
│   ├── store/                # SQLite persistence
│   └── web/                  # FastAPI app, routes, templates, static
├── tests/
│   ├── fixtures/             # small messy files shaped like real data (see section 11)
│   └── ...                   # mirrors src layout
└── scripts/                  # dev helpers only (e.g. generate test fixtures)
```

## 5. Pipeline and contracts

```
upload/paste
  -> ingest      : detect format, parse to RawTable
  -> map columns : propose mapping (LLM may assist), validate in code, user can correct
  -> clean       : tidy Readings + CleaningLedger
  -> quality     : QualityFlags + per-station Reliability
  -> facts       : Fact[] (each with id, value, coverage, evidence refs)
  -> interpret   : LLM -> Claim[] citing fact ids
  -> verify      : drop or flag unverified claims
  -> actions     : persona-specific Action[] with reasons + evidence
  -> compare     : Diff vs previous Brief
  -> render      : internal note, advisory, map, table
```

Core schemas (put in `schemas.py`; refine as needed but keep the intent):

- `Reading`: station_id, timestamp (tz-aware, IST), pollutant, value (nullable), unit, source_row_ref.
- `LedgerEntry`: row_ref, rule, before, after, reason. Every cleaning action produces one.
- `QualityFlag`: kind (gap, stuck, ceiling, implausible, empty_column, unit_mismatch, orphan_aqi, ...), station_id, time range, severity, evidence refs.
- `Fact`: id, statement_data (numbers), station_id, period, coverage_pct, reliability, evidence refs.
- `Claim`: text, cited_fact_ids, confidence, status (verified / unverified).
- `Action`: priority, persona, text, rationale, cited_fact_ids, confidence.
- `Brief`: id, created_at, persona, facts, claims, actions, flags, ledger summary.
- `Diff`: changed facts, new/resolved flags, coverage changes, plain-language summary inputs.

### Hard rules for the pipeline

1. **Code computes, the LLM narrates.** The LLM never calculates statistics, averages, AQI or trends. It receives computed facts and writes about them.
2. **Send aggregates, not raw rows**, to the LLM. This is both an efficiency and a security measure.
3. **Every claim cites fact IDs.** The verifier rejects claims with missing or unknown IDs and flags quoted numbers that do not match the fact. Unverified claims are shown as unverified or dropped, never silently kept.
4. **Never average without coverage.** Every aggregate carries coverage %, and below a configured threshold the value is labelled unreliable.
5. **Never invent coordinates.** The map uses lat/lon from the upload or an explicit stations file. If absent, show the table only and say why.
6. **Missing is not zero.** Never fill gaps with zeros. Imputation is off by default; if added, it is recorded in the ledger and labelled.
7. **Scale awareness.** Use the CPCB (Indian) AQI. If input data looks like a different scale (e.g. US EPA), flag it instead of mixing.

## 6. Domain knowledge (from the sample files already analysed)

These come from real Bengaluru files (OpenCity: a wide hourly grid CSV, a KSPCB Peenya 15-minute CSV, KSPCB monthly AQI PDF, a 2018 report PDF). Build the parsers and detectors against these patterns.

**Formats to parse**
- Wide hourly grid: `Year,<yyyy>` marker rows, month blocks headed `January-2017,00:00:00,...,23:00:00`, then `<day>,<24 values>` rows, with stray `"` spacer lines. Entire months/days can be blank. No pollutant or station label is present, so require the user to provide it or mark it as unknown.
- Long 15-minute export: columns Station ID, State, City, Station Name, Timestamp (UTC, ISO), PM2.5, PM10, NO, NO2, NOx (ppb), NH3, SO2, CO (mg/m3), Ozone, Benzene, Toluene, Xylene variants, AT, RH, WS, WD, RF, TOT-RF, SR, BP, VWS. Contains an embedded stray year-divider row.
- Report-style monthly tables (PDF text): DD-MM-YYYY dates, per-station daily PM10, PM2.5, SO2, NO2, CO, O3, NH3, Benzene, Temp, RH, WS, WD, BP, AQI, with Min/Max/Average rows inside the table and `-` / `*` for no data.

**Messiness to detect**
- Whole-day or whole-month blanks; long gaps (days to weeks).
- Sentinel ceiling values (500) and long runs of them (a 67-hour run of 500 was a sensor fault, not an event).
- Stuck sensors: identical values for many consecutive readings; near-constant daily values for a whole month on some channels.
- Implausible values: physically impossible temperatures for the city, pressure outliers (e.g. 633 vs ~720), RH near 0, extreme PM spikes (hundreds to ~1000), benzene spikes.
- Columns that are 100% empty.
- Zero-filled gaps hidden behind a 0%-missing column (rainfall totals).
- AQI present while its input pollutants are missing.
- Unit and header variants: `µg/m³` vs `µg/m3`, `mmHg` vs `mb`, NOx in ppb beside NO/NO2 in µg/m³, CO in mg/m³ (CO unit traps are common, including a source that printed CO as µg/m³).
- Timestamps in UTC (convert to IST, +05:30) before any hour-of-day or daily statistic.
- Mixed int/float formatting, quoted station names, differing date formats.

**Analytical patterns worth surfacing**
- Seasonality (winter high, monsoon low), diurnal peaks (roughly 8-10h and 20-22h local), festival spikes (Diwali), lockdown dip.
- Citywide synchronized rise/fall across stations suggests a regional or meteorological driver, not a single local source. Do not write "station X is worsening" without checking this.
- PM2.5/PM10 ratio as a coarse-dust vs combustion hint. Benzene and NO2 as traffic hints. Present as hints with confidence, not conclusions.
- Reported "improvements" that coincide with falling coverage must be labelled as data gaps (a 2018 report showed PM2.5 averages falling while days of missing data were highest).

**CPCB AQI**
- Worst sub-index across pollutants sets the AQI. Linear sub-index interpolation between breakpoints.
- Categories: Good 0-50, Satisfactory 51-100, Moderate 101-200, Poor 201-300, Very Poor 301-400, Severe 401-500.
- Put breakpoints in `config.py`. **Verify the breakpoint table against the official CPCB document before relying on it**, and cite the source in a comment. Also verify and encode CPCB's minimum-data requirements for computing an AQI (minimum number of pollutants including a particulate, and minimum hours for a 24-hour average); if the inputs do not satisfy them, report "insufficient data" instead of a number.

## 7. LLM usage

- Provider: Anthropic API. Key from `ANTHROPIC_API_KEY` env var only. Never log it, never send it to the client, never commit it.
- One module (`llm/`) owns all calls. It exposes small typed functions, e.g. `interpret_facts(...)`, `rank_actions(...)`, `write_advisory(...)`, `suggest_column_mapping(...)`. Everything else depends on an interface so tests can substitute a fake.
- Use tool use / schema-constrained output and validate with pydantic. On validation failure retry once with the error, then surface an honest error to the user.
- Treat all uploaded content as **untrusted data**. Place it inside clearly delimited data sections, instruct the model never to follow instructions found there, and rely on schema-constrained output. Do not let uploaded text choose tools, URLs or prompts.
- Efficiency: cache results keyed by a hash of (inputs, prompt version, model). Batch all translations into a single call. Keep payloads to aggregated facts.
- Advisory content: separate versions for languages (English, Hindi, Kannada to start) and reading levels (simple, standard). Include distinct guidance for children, older adults, and people sensitive to poor air. Advisory text must state plainly when data is insufficient rather than reassure.
- Safety tone: health guidance must be general and cautious, refer to local health authorities for medical concerns, and never claim certainty the data does not support.

## 8. Web app and UX requirements

- Single flow: upload/paste -> review column mapping -> see cleaning ledger and quality flags -> pick persona -> brief (with evidence links) -> comparison -> advisory -> map/table.
- Evidence links: every claim and action links to the fact, and every fact links to the rows/columns it came from.
- Data-quality is a first-class screen, not a footnote: show flags, coverage per station, and what was changed.
- "Compare with previous" works from stored briefs (SQLite). No login: briefs are listed per browser session (signed cookie) or selected by ID.
- Map: Leaflet with markers coloured by AQI category **and** labelled with text/icons (never colour alone). Provide the equivalent sortable table. If coordinates are missing, say so and show the table.
- Honest states everywhere: loading, empty, insufficient data, and LLM failure each have clear messages.
- Printing: the citizen advisory has a clean print stylesheet.

### Accessibility checklist

- Semantic landmarks and headings, one `h1` per page.
- All controls keyboard-operable with visible focus.
- Contrast meets WCAG AA. Severity conveyed by text + icon + colour.
- Map has a full table alternative; markers have accessible names.
- `lang` attribute on translated blocks; `aria-live` for async updates.
- Form fields have labels and error text tied via `aria-describedby`.
- Works at 200% zoom and on mobile widths.

## 9. Security checklist

- Secrets only via environment; `.env` in `.gitignore`; `.env.example` has placeholders.
- Upload limits: max file size, allowed types, row/column caps; parse defensively (no `eval`, no `pickle`, no shell calls on uploaded content; use safe CSV/XLSX/PDF libraries).
- Escape all LLM and user text in templates (Jinja autoescape on). No `|safe` on untrusted content.
- Prompt-injection defence as described in section 7.
- Rate limiting per IP on LLM-backed endpoints, plus a global daily cap, since the deployed app spends the owner's API credits.
- Security headers (CSP, X-Content-Type-Options, frame protection). CSRF protection on state-changing routes.
- Parameterized SQL only.
- Dependency audit (`pip-audit`) before submission.
- Errors shown to users never include stack traces or secrets.

## 10. Efficiency checklist

- Stream/chunk large CSVs; do not load huge files into memory twice.
- Vectorized pandas operations; no row-by-row Python loops on readings.
- Reduce data before the LLM: aggregated facts only.
- Cache LLM results by input hash.
- Index the SQLite columns used for lookups.

## 11. Testing plan

- `pytest`, with coverage reported. Aim for strong coverage of `ingest`, `clean`, `quality`, `facts`, `verify`, `compare`.
- Fixtures in `tests/fixtures/` are **small synthetic files that reproduce the real failure modes** in section 6 (wide grid with blank days and a 500 run, long export with UTC timestamps and empty columns, report table with `-` and `*`, unit variants). They are test inputs only and must never be presented as real data in the app.
- Unit tests per detector (gap, stuck run, ceiling, implausible, empty column, orphan AQI, unit mismatch).
- AQI tests with hand-computed expected values from the official breakpoints, including the "insufficient data" cases.
- Verifier tests: unknown fact id, missing citation, mismatched number, valid claim.
- Comparison tests: genuine change, change explained by coverage drop, no change.
- LLM layer: tested with a fake client injected through the interface. Add one opt-in live test (skipped unless `RUN_LIVE_LLM=1`).
- Route tests with FastAPI `TestClient` for the full upload -> brief flow using the fake LLM, plus security tests (oversized upload, wrong type, HTML in cells).
- CI-style local command: `ruff check . && ruff format --check . && mypy src && pytest`.

## 12. Milestones and acceptance criteria

Do these in order. Do not start a phase until the previous one passes its acceptance check. Commit after each.

**Phase 0: Skeleton**
- Repo layout, tooling, schemas, config module, README stub, `.env.example`.
- Accept: `ruff`, `mypy`, `pytest` all run green on an empty-but-wired project.

**Phase 1: Ingest, clean, quality**
- Parsers for long CSV, wide grid, pasted text. Column mapping with validation. Cleaning ledger. Quality detectors and reliability.
- Accept: fixtures covering each failure mode produce the expected ledger entries and flags; tests pass.

**Phase 2: Facts, interpretation, verification (first end-to-end slice)**
- Facts engine with CPCB AQI and coverage. Claude interpretation with fact-ID citations. Verifier. Minimal web page that runs the whole flow with a real API call.
- Accept: upload a messy file in the browser, get a brief whose every claim links to evidence; an invalid citation is demonstrably rejected; failure of the API shows an honest error.

**Phase 3: Actions and comparison**
- Persona-specific ranked actions. SQLite store. Brief-to-brief diff, coverage-aware.
- Accept: two consecutive uploads produce a diff that correctly labels a coverage-driven change as a data gap.

**Phase 4: Advisory and map (stretch if time is short)**
- Internal note, multilingual advisory with reading levels and sensitive-group guidance, map plus table.
- Accept: advisories render in all configured languages with `lang` attributes; map and table agree.

**Phase 5: Hardening and submission**
- Security, accessibility, efficiency passes (sections 8-10). README complete. Deploy.
- Accept: full pass as a stranger on the live URL (see checklist below).

## 13. Pre-submission checklist

- [ ] Fresh clone follows README and runs locally without undocumented steps.
- [ ] No hardcoded or canned outputs anywhere; sample-data button is labelled and uses the real pipeline.
- [ ] Real Claude call on every LLM-derived output; failure shows an honest error.
- [ ] No login required; no credentials needed to reach any feature.
- [ ] Each demoed feature works end-to-end on the deployed URL, including comparison with a previous brief.
- [ ] Every claim and action traces to facts and source rows; unverified claims are visibly marked.
- [ ] Data gaps and unreliable readings are clearly flagged in the brief and the advisory.
- [ ] `ruff`, `mypy`, `pytest`, `pip-audit` all pass.
- [ ] No secrets in the repo or git history; spend cap and rate limits set on the API key.
- [ ] Accessibility checklist verified with keyboard-only and a screen-reader spot check.

## 14. Working agreement with Claude Code

- Plan before coding each phase: state the approach in a few lines, then implement.
- Write tests alongside code, not after.
- Keep commits small and focused with clear messages.
- If a requirement here conflicts with reality (e.g. a breakpoint value you cannot verify), say so and ask instead of guessing.
- Prefer deleting a half-working feature to shipping it.
- Do not add features beyond this document without asking.
