# Matched electoral validation and cohort bootstrap

The website now uses the original four-option Senate answers without a historical
correction. The original 100-draw projection and time-series plot construction
are preserved.

## Matched evaluation

`config/validation_house_2026.yaml` and `config/validation_president_2024.yaml`
specify the manuscript's questions and response options. They use Jev 1.13,
Mercury Decide, and Decider V1.2, the original `sample_100` cohorts, nine persona
characteristics, sentence descriptions, role-play, and no news. House responses
include **Not sure**, not third-party voting. Presidential third-party candidates
are grouped into one option as in the manuscript. House question wording follows
the manuscript; it has not been verified as a verbatim CES questionnaire quote.

```powershell
# Score saved, matching evaluation responses without making API calls.
.venv/Scripts/python.exe src/validate_electoral_responses.py
# Explicitly collect/resume paid requests, then score both evaluations.
.venv/Scripts/python.exe src/validate_electoral_responses.py --collect
```

The presidential `backcast-2024` run is reused only after reconciling its recorded
request configuration, persona text, models, CES answer fields and all draw IDs.
The newly collected House run is `validation-house-2026`. The script will not use
ordinary Senate responses as House evaluation responses.

For every state, model, question and category, the prediction is the average
probability and the reference is the frequency of that category in the same
eligible draw positions. Missing survey answers are excluded from both sides;
Not sure is a substantive House answer. Repeated respondents count per draw;
survey weights are not applied again. Signed difference in percentage points is
`100 * (predicted - reference)`. Outputs in `data/model_validation/` are
`matched_state_categories.parquet`, `matched_coverage.parquet` and
`matched_manifest.json`. No fitted correction or comparison with official state
election totals is used in this website evaluation.

## Four-category bootstrap

`src/bootstrap_responses.py` creates 10,000 replicates per model/day/state. Each
replicate selects **100 original draw positions uniformly with replacement** and
averages all four probability columns together. Repeated positions retain their
original multiplicity. The point estimate remains the original cohort mean.

The reported bootstrap standard error (SE, or SEM for the response mean) is the
sample standard deviation of the 10,000 replicate means, using `ddof=1`. It is
**not divided by sqrt(10000)**. Table errors are expressed in percentage points.
All four category summaries are exported under `docs/data/`.

Within each replicate the largest of the Democratic, Republican and third-party
means wins the state. Non-voting remains in the probability vector but does not
win a seat. Exact ties are unallocated. The 65 fixed seats are then added.
Independent/other and unallocated seats are retained so every replicate totals
100 seats. The headline shows the original seat estimate plus/minus the SD of
bootstrap seat totals, and a compact stacked-dot plot summarising all replicates on one shared axis.
There are 50 display dots total (25 per party); each represents approximately 4%
of its party distribution, allocated to seat-count bins by largest-remainder
rounding. Estimates and SEs appear at the top-left inside the plot. Other seat
categories are computed but not plotted.

This measures variation from the finite persona cohort, conditional on the saved
model responses. It does not measure model error, the original survey design,
future political change, or actual election-winning probabilities. Standard
errors are not confidence bounds and need not be centred on bootstrap medians.

The website build exports response summaries, Senate summaries and all Senate
replicate totals as Parquet under `docs/data/`. Model/day/state seeds are stable,
so adding new reporting days does not alter earlier replicates. The jitter plot
code is unchanged; only its accompanying table adds bootstrap SEs.

## Displaying the external benchmark and evaluation

Missing external-forecast days reuse the most recent earlier actual snapshot.
Reused markers and table dates carry an asterisk; tooltips show the source date.
No value is filled before the first available benchmark, synthetic model gaps
remain gaps, and original downloaded snapshots are not edited. The build makes
no additional provider calls.

Matched evaluations are paired-dot charts: filled points are model category
means, open points are recorded CES frequencies, and labels give signed pp
differences. Exact values remain in collapsible tables. One-off House and presidential evaluation costs are not displayed on the website.
The main daily-run costs remain. Saved usage metadata is retained for reproducibility.

The evaluation overview averages each model/category proportion equally across
the 35 states, separately for the two questions. It does not pool respondents
or weight states by population. State-level plots remain selectable below the
two overview plots. Overview values are exported in
`docs/data/evaluation_state_averages.parquet`.
