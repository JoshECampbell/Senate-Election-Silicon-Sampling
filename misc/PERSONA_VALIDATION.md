# Persona validation

## Purpose

`src/validate_personas.py` compares each state's sampled personas with the CES respondents from that state. It answers one question: do the sampled draws have similar marginal distributions to the weighted CES reference data?

It does **not** establish that CES is a census of the state, that joint distributions are preserved, or that election forecasts are accurate.

## Run it

From the repository root:

```sh
uv sync
uv run python src/validate_personas.py --run-name test
```

The command reads `data/personas/test/` and writes results to `data/persona_validation/test/`.

Useful options:

```sh
# Compare selected states only.
uv run python src/validate_personas.py --run-name test --states Alabama "New Hampshire"

# Compare a different set of variables.
uv run python src/validate_personas.py --run-name test --features age race pid3 sexuality educ gender4

# Use a different persona directory or reference dataset.
uv run python src/validate_personas.py --run-name pilot --personas data/personas/custom --data-path data/cleaned/cleaned_CES_data.parquet
```

Default features and age groups are in `config/persona_validation.yaml`. Command-line options override that file.

The default comparison covers the exact 11 persona characteristics: race/ethnicity,
gender, state of residence, education, religion, marital status, sexual orientation,
voter registration, family income, seven-category party identification, and ideology.
Age remains available as an optional check but is not one of these 11 prompt fields.

To refresh the website's three existing cohort comparisons (without resampling):

```sh
uv run python src/validate_personas.py --run-name sample_25
uv run python src/validate_personas.py --run-name sample_50
uv run python src/validate_personas.py --run-name sample_100
```

The website displays six characteristics selected in `docs/site-config.yml`:
race/ethnicity, gender, education, marital status, voter registration, and party
identification. The saved validation files retain all 11 characteristics.
The website plots the 100-draw cohort and shows TVD for all three cohorts beneath
the plots. Both use the same state selector. Table distances are on the 0-1 scale;
the plot annotations express the same distance as a percentage. State of residence
has distance zero by construction and does not provide an independent test of fit.
These are single saved cohorts per sample size, not repeated simulation estimates.

## Method

For each selected state and feature:

- **Reference share** = sum of CES `commonweight` in a category / sum of CES `commonweight` in the state.
- **Persona share** = persona draws in a category / all persona draws in the state.
- **Difference (percentage points)** = `100 × (persona share − reference share)`.
- **Total variation distance** = half the sum of absolute category-share differences. Zero means the two distributions are identical for that feature.

Persona draws use equal weight because the sampler already draws CES rows with probabilities proportional to `commonweight`. Repeated draws remain repeated draws.

The script checks that every persona row belongs to its claimed state and matches the referenced CES respondent for every compared feature. It rejects empty files, duplicate/missing reference identifiers, invalid reference weights, and altered persona values.

Age is calculated as `age_reference_year - birthyr`. Nulls, `Skipped`, and `Not Asked` are grouped as `No response`; unexpected codes remain visible as their own categories. Every category is included in both distributions, including zero-count categories.

## Outputs

Each run writes:

| File | Contents |
| --- | --- |
| `<run-name>_distributions.parquet` | One row per state, feature, and category: counts, weighted reference shares, persona shares, and differences. |
| `<run-name>_summary.parquet` | One row per state and feature: total variation distance and largest absolute difference. |
| `<run-name>_validation.yaml` | Reference dataset path, persona directory, total draws, and each state's persona file, draw count, and CES reference count. |
| `plots/<state>.png` | Paired bars of persona and weighted CES shares. |

The YAML file is intentionally short provenance metadata. It does not contain hashes, settings, labels, weight totals, or output paths; the configuration and output tables already provide those details.

## Interpret results

A positive percentage-point difference means the category occurs more often among persona draws. Smaller total variation distances mean closer agreement for that feature. Neither metric is a significance test or pass/fail threshold: random sampling produces variation, especially for small states or small numbers of draws.

Review multiple features, sample sizes, and the underlying CES limitations before using the results as forecasting evidence.

## Verify implementation

```sh
uv run python -m unittest discover -s test -p "test_validate_personas.py" -v
```

The tests cover weighted reference shares, repeated draws, missing and unknown responses, age boundaries, invalid weights, source mismatches, and CLI output.
