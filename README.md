# Senate Election Silicon Sampling

Sample CES respondents within each state, query decision models, validate the
responses, and publish synthetic Senate results with Quarto. These are synthetic
responses, not observations from a voter poll.

## Setup

```powershell
uv sync
```

Copy `.env.example` to `.env` and add `OPENROUTER_API_KEY` before live queries.
No API key is required to build the website from saved results.

## Data and personas

The current data pipeline is:

```powershell
uv run python src/raw_data_pull.py
uv run python src/data_cleaning.py
uv run python src/create_personas.py --run-name sample_100 --samples 100 --seed 42
uv run python test/validate_personas.py --run-name sample_100
```

Only run these when you intend to download or regenerate those inputs. The
website reuses the saved persona sample across dates; do not regenerate it for
an ordinary daily update. Raw data is in `data/raw/`, selected CES fields in
`data/cleaned/`, and sampled personas plus their YAML settings in `data/personas/`.
The download script retrieves the CES 2025 Common Content tab file from Dataverse;
it does not currently verify a published checksum.

Persona validation compares draw frequencies against the weighted CES state
reference, retaining repeated draws. It writes tables, plots and metadata under
`data/persona_validation/`. See [the validation guide](misc/PERSONA_VALIDATION.md)
and [validation settings](config/persona_validation.yaml).

## Daily model queries

Use the actual Toronto reporting date in the run name. For example:

```powershell
uv run python src/query_llms.py --run-name 2026-10-28-all-models --personas data/personas/sample_100 --persona-level 9 --persona-format sentence --prompt-style role_play --models jev mercury decider
```

Add `--dry-run` to inspect requests without calling providers. `--smoke-test`
sends one live request per selected model. Live requests may incur charges.
Mercury currently uses the paid model. Model IDs, prompts and response options
are in [query_config.yaml](config/query_config.yaml).

Each unique state/respondent/configuration is queried once, then expanded back
into its sampled rows. Four probabilities are retained: Democrat, Republican,
Third party, and Would not vote. Held-out vote outcomes are not included in prompts.

Each run writes `results.parquet`, `summary.parquet`, `run_metadata.json`, and an
append-only, gitignored `responses.jsonl` under `data/llm_responses/<run-name>/`.
Probabilities must be finite, between 0 and 1, and sum to 1 within `1e-6`.
Unresolved responses receive up to three validation retries. Resuming reuses
compatible records and preserves the retry budget; changed requests require a
new run name. Query summaries average valid sampled rows, preserving multiplicity.
The website applies the stricter requirement of all 100 valid responses per state.

## Website

All website files live in [`docs/`](docs/README.md). After saving a daily run:

```powershell
quarto render docs
uv run python docs/_tools/check_website.py
```

Rendering discovers dated runs and prepares figures offline. Unchanged figures
are reused. Commit/push `docs/` and configure GitHub Pages to deploy from your
branch's `/docs` folder. See the [website workflow](docs/README.md) for the local
Quarto executable path, folder layout and preview command. No daily query schedule
or custom publishing workflow is currently enabled.

## Offline tests

```powershell
uv run python -m unittest discover -s test -p 'test_*.py' -v
uv run python -m unittest discover -s docs/_tools -p 'test_*.py' -v
```

The tests use synthetic fixtures and mocked provider calls. Website controller
checks are described in `docs/README.md`.
