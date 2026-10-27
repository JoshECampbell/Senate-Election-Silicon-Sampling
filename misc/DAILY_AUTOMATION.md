# Daily collection and website publication

Code, writing, tests and Actions definitions stay on `main`. `daily-data` is an
automatically maintained, data-only branch in this same repository. You do not
create it manually or merge it into `main`.


## What runs

**Daily data** (`.github/workflows/daily-data.yml`) runs at 9:00 a.m.
America/Toronto each day (or manually), freezes the Toronto date,
then runs the configured models independently in parallel with polling.
`config/daily_run.yaml` is the executable counterpart of the command in
`config/oct_26_run.md`: same saved sample, level 9, sentence, role_play, no news,
Jev/Mercury/Perplexity and no Luna. Folders are `oct-28-no-luna`, `oct-29-no-luna`,
then `nov-01-no-luna`, etc. Provider IDs remain in `config/query_config.yaml`.

The query runner validates responses and applies its existing bounded retries.
One model/provider failure cannot cancel another model. A model counts as
publishable only with all 35 states and 100 valid draws per state. Failed models
remain unavailable for that date; Latest/headline views can show their prior
complete result with its actual date. Failed attempts still contribute to costs.

The polling job requires 35 unique study races and `asOf` equal to the reporting
date. On failure it writes no new observation. Earlier polling remains available
for Latest, and historical dates never silently substitute an earlier snapshot.

The archive job combines and saves observations even when every model failed.
It does not make plots or
render HTML. The first archive also seeds history from `main`, preserving prior
costs from the already published data manifest when raw logs are unavailable.

**Website** (`.github/workflows/website.yml`) starts after collection completes
or when run manually. It checks out current `main`, restores observations and:

- After daily collection, publishes only if at least one model has a complete,
  independently reconciled result. If all three failed, the live site stays put.
- For a manual website run, rebuilds using saved observations regardless of
  that morning's failures. Rendering makes no model calls or polling fetches.
- Generates plots, updates costs and renders HTML, then deploys successful
  builds from `main` through the `github-pages`
  environment. It does not commit generated HTML or plots back to `main`.

There are no PR/push triggers and no automated test suites. The existing runtime
response validation, bounded retries and publication-completeness checks remain.
All test scripts are still available to run manually. The prose in
`docs/index.qmd` is never rewritten by collection or rendering.

Real raw-CES tests remain local because the raw download is gitignored. They
can still be run with the full Python suite; CI does not redownload it daily.

## What daily-data stores

```text
data/llm_responses/oct-28-no-luna/
  results.parquet, summary.parquet       combined dated results
  run_metadata.json, usage_summary.json publication status and cumulative costs
  models/jev/ ...                        each model's outputs and resume.json
data/polling_forecast/YYYY-MM-DD.json     original dated forecast and retrieval time
data/daily_runs/RUN_ID.json               collection outcome and source commit
```

`resume.json` retains the latest attempt per request and its retry count, with
a request hash replacing the prompt payload. Raw bodies, prompts and raw JSONL
logs are excluded from checkpoints. Results retain their existing research
columns. Usage summaries preserve all attempts, including retries and output
tokens, so future renders do not need raw logs to reproduce costs.

Rerunning a collected day restores checkpoints, reuses successful responses and
preserves the original retry budget. Changing actual request inputs for that
same day is rejected by the runner; use a new reporting day/study run instead.
Artifacts transfer job outputs for seven days; the branch is the permanent
archive. Cosmetic edits never change the archive schema. Changes to study
conditions/schema need a deliberate update to collection and website settings.

## Local commands (from the repository root)

```powershell
# Restore archived observations without switching your working branch.
uv run python src/daily_storage.py restore

# Rebuild from saved data, without fetching polling again.
$env:SKIP_FORECAST_FETCH = '1'
quarto render docs
Remove-Item Env:SKIP_FORECAST_FETCH
uv run python test/check_website.py

# Offline automation tests: temporary local Git repositories and mocked queries.
uv run python -m unittest discover -s test -p 'test_daily_automation.py' -v
```

For normal local renders, `quarto render docs` still fetches current polling.
Merge website edits through the usual feature branch > PR > main process.
They appear on the next daily rebuild, or immediately after manually running
**Website** on `main` in the Actions tab.
