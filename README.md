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
uv run python src/validate_personas.py --run-name sample_100
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

Website sources and rendered assets live in [`docs/`](docs/README.md), build
scripts in `src/`, and checks in `test/`. After saving a daily run:

```powershell
quarto render docs
uv run python test/check_website.py
```

Rendering fetches and archives the public Polling Forecast Senate benchmark,
then discovers dated runs and prepares figures offline. Unchanged figures
are reused. The Website Actions workflow builds from current `main` plus archived
observations, tests the result, and deploys directly to GitHub Pages. PRs build
and test without deploying. See the [website workflow](docs/README.md) for local
preview commands and the [automation guide](misc/DAILY_AUTOMATION.md) for activation.

## Daily automation

After activation, **Daily data** collects at **9:00 a.m. America/Toronto** using
`config/daily_run.yaml`, matching the study command in `config/oct_26_run.md`.
Models run independently; one complete model is enough to update the site.
Missing polling falls back to its most recent saved date. If every model fails,
the daily publication is skipped. Merging writing or code changes into `main`
still rebuilds the site using saved data, without paid requests.

The workflow creates and maintains `daily-data` automatically. It holds only
observations, costs and retry checkpoints; workflows, tests, website sources and
writing stay on `main`. You never need to merge the data branch into `main`.

**Activation:** add Actions secret `OPENROUTER_API_KEY`, select **GitHub Actions**
as the Pages source, and merge this implementation into `main`. The first
scheduled/manual collection creates the storage branch. Details, failure rules,
reruns and manual controls are in [DAILY_AUTOMATION.md](misc/DAILY_AUTOMATION.md).

## Data checks and offline tests

The real-data checks require the saved raw and cleaned CES files. They verify
17,000 rows, the 17 required codebook variables, storage types, allowed codes,
unique IDs, positive finite weights, adult birth years and exact preservation
of selected raw values. Missing files fail rather than being silently skipped.

The separate simulated-data tests apply the same schema/range checks to a saved
128-row artificial cleaned-CES fixture. It has no real respondents and is not a
research dataset. Regenerate it reproducibly with:

```powershell
uv run python src/simulate_cleaned_ces.py
```

Run all Python tests, or just one data test script:

```powershell
uv run python -m unittest discover -s test -p 'test_*.py' -v
uv run python -m unittest discover -s test -p 'test_ces_data.py' -v
uv run python -m unittest discover -s test -p 'test_simulated_ces_data.py' -v
```

Query tests use synthetic fixtures and mocked providers; no tests send live LLM
requests. All test scripts start with a bullet list describing their checks.
The rendered-bundle check and JavaScript controller checks are described in
`docs/README.md`.
