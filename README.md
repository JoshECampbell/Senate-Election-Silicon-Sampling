# Senate-Election-Silicon-Sampling

## CES Common Content 2025 raw data

`scripts/download_ces_common_content_2025.py` downloads the released Cumulative
CES Common Content v12.0 Feather file from Harvard Dataverse, verifies its
published MD5 checksum, and saves the unmodified 2025 subset as
`data/raw/ces_common_content_2025_raw.parquet`. Its adjacent JSON metadata
marks the file as `raw`. Parquet is the project's standard data format.

Install the dependency, then download and test the data:

```sh
python -m pip install -r requirements.txt
python scripts/download_ces_common_content_2025.py
python tests/test_ces_common_content_2025.py
```

The integrity test requires the raw Parquet file to exist and verifies that it
has exactly 17,000 unique, non-missing `case_id` respondents, all from 2025.

## Querying the decision models

`src/query_llms.py` gives each persona to two decision models on OpenRouter's
Decisions API (TypeSafe Jev and OpenAI's `gpt-6-luna-decisions`) and asks one
four-option question: Democrat, Republican, Third party, Would not vote. Both
APIs return a probability for every option, and all four are saved. Prompts,
options, persona fields and model IDs live in `config/query_config.yaml`.
The held-out outcomes (`CC25_363`, `presvote24post`) are never sent to a model.

```sh
cp .env.example .env                  # then add your OPENROUTER_API_KEY
uv run python src/query_llms.py --run-name pilot --dry-run     # print the requests, no API calls
uv run python src/query_llms.py --run-name pilot --smoke-test  # one live call per model
uv run python src/query_llms.py --run-name pilot --limit 5     # 5 personas per state
uv run python src/query_llms.py --run-name grid --persona-level 3 9 11 \
    --prompt-style role_play prediction population             # full grid
```

Results go to `data/llm_responses/<run-name>/`: `results.parquet` (one row per
persona x configuration), `summary.parquet` (mean probabilities by state),
`run_metadata.json` (config, arguments and git commit for each invocation) and
`responses.jsonl` (raw requests and responses; gitignored because it gets large).
Re-running a `--run-name` skips anything already answered.

## Validate the sampled personas

Compare each state's personas with its weighted CES reference respondents:

```sh
uv sync
uv run python test/validate_personas.py --run-name test
```

The default features are age, race, party identification, sexual orientation,
and education. Use `--features` to change them. Use `--states` to select states.
The script saves Parquet tables, PNG plots, and YAML metadata under
`data/persona_validation/<run-name>/`.

Read the [validation guide](docs/PERSONA_VALIDATION.md) for the method, commands,
outputs, and interpretation. Change the defaults in
[persona_validation.yaml](config/persona_validation.yaml).
