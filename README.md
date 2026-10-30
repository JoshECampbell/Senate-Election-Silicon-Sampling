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
observations and deploys directly to GitHub Pages after daily collection or a
manual run. There are no PR or push-triggered checks. See the [website workflow](docs/README.md) for local
preview commands and the [automation guide](misc/DAILY_AUTOMATION.md) for activation.

## Daily automation

After activation, **Daily data** collects at **9:00 a.m. America/Toronto** using
`config/daily_run.yaml`, matching the study command in `config/oct_26_run.md`.
Models run independently; one complete model is enough to update the site.
Missing polling falls back to its most recent saved date. If every model fails,
the daily publication is skipped. Writing or code changes merged into `main`
appear on the next daily rebuild. To publish them sooner, manually run
**Website** from the Actions tab; that uses saved data without paid requests.

The workflow creates and maintains `daily-data` automatically. It holds only
observations, costs and retry checkpoints; workflows, tests, website sources and
writing stay on `main`. You never need to merge the data branch into `main`.

**Activation:** add Actions secret `OPENROUTER_API_KEY`, select **GitHub Actions**
as the Pages source, and merge this implementation into `main`. The first
scheduled/manual collection creates the storage branch. Details, failure rules,
reruns and manual controls are in [DAILY_AUTOMATION.md](misc/DAILY_AUTOMATION.md).

## Model validation

`src/validate_electoral_responses.py` compares separate matched-question model
requests with the sampled respondents' recorded CES answers. The House request
includes Democratic, Republican, non-voting and Not sure options. The presidential
request groups Harris, Trump, third-party voting and non-voting as in the manuscript.
Both use the original sample_100 cohorts and nine-characteristic sentence role-play.
Ordinary daily Senate responses are not treated as answers to the House question.

```powershell
# Score saved matched responses, with no provider calls.
uv run python src/validate_electoral_responses.py
# Explicitly collect/resume paid evaluation requests and then score them.
uv run python src/validate_electoral_responses.py --collect
```

Outputs in `data/model_validation/` include matched state/category percentages,
signed percentage-point differences, eligible-draw counts and a provenance manifest.
The existing matching 2024 run is reused after checking configuration and draw IDs.
The website displays these comparisons by state; no correction is fitted or applied.
The earlier `validate_models.py` remains available for legacy diagnostic outputs,
but those two-party/official-result charts are no longer the website evaluation.

## Forecast and bootstrap ranges

The website uses `src/bootstrap_responses.py` to resample all four response
probabilities together 10,000 times, selecting 100 original draw positions per
state with replacement and equal probability. Original draw multiplicities carry
survey weighting, so weights are not applied again. The original cohort mean is
preserved; its bootstrap standard error is the SD of the 10,000 replicate means,
not that SD divided by sqrt(10000). The time-series table adds this error in pp;
the jitter plot itself is unchanged.

Each replicate applies the classic seat rule to the four-category averages:
the largest Democratic, Republican or third-party mean wins, non-voting cannot
win, and exact ties are unallocated. Adding the 65 fixed seats yields the full
Senate. The headline retains the original projection and adds Democratic and
Republican stacked-dot distributions (50 display dots total, summarising 10,000 replicates) and original seat counts plus/minus
bootstrap SE. All seat categories are retained in downloadable replicate totals.
No national/state noise or historical correction is added.

These are cohort-resampling summaries conditional on saved model responses, not
actual election-winning probabilities or comprehensive population uncertainty.
Stable model/day/state seeds preserve earlier replicates when new days are added.
Website builds write response summaries, Senate summaries and Senate draws under
`docs/data/`. See [the detailed method](misc/MATCHED_VALIDATION_AND_BOOTSTRAP.md).
The older `src/forecast.py` is a separate two-party diagnostic and is no longer
used by the website.

## Data checks and offline tests

The real-data checks require the saved raw and cleaned CES files. They verify
17,000 rows, the 17 required codebook variables, storage types, allowed codes,
unique IDs, positive finite weights, adult birth years and exact preservation
of selected raw values. Missing files fail rather than being silently skipped.

`src/simulate_data.py` simulates the whole study before the real data: a
17,000-row CES-like frame with linked variables, 100 weighted personas per
Senate state, three models' answers on three run days (with refusals, errors
and malformed vectors injected), and 1,000 forecast draws of every state and
the seat count. Outputs are in `data/simulated/` (see its README). The
simulated-data tests apply the real-data schema/range checks to the frame
(`test_simulated_ces_data.py`) and check relationships between variables, the
response rules and the forecast (`test_simulated_pipeline.py`). Regenerate with:

```powershell
uv run python src/simulate_data.py
```

Run all Python tests, or just one data test script:

```powershell
uv run python -m unittest discover -s test -p 'test_*.py' -v
uv run python -m unittest discover -s test -p 'test_ces_data.py' -v
uv run python -m unittest discover -s test -p 'test_simulated_*.py' -v
```

Query tests use synthetic fixtures and mocked providers; no tests send live LLM
requests. All test scripts start with a bullet list describing their checks.
The rendered-bundle check and JavaScript controller checks are described in
`docs/README.md`.
