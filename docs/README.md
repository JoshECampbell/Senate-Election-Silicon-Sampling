# Website: edit, build, publish

Everything specific to the website lives here. Both the editable Quarto source
and the rendered page are in this folder; GitHub Pages serves `docs/index.html`.
The build reads saved analysis data elsewhere in the repository. It never queries
LLMs or changes those inputs. Rendering also fetches the public Polling Forecast
Senate benchmark before preparing the figures.

## Polling Forecast benchmark

`_tools/polling_forecast.py` explains the workflow and calculation at the top.
Each render makes one public API request and archives the response in
`data/polling_forecast/YYYY-MM-DD.json` at the repository root, using `asOf`.
The most recent successful retrieval replaces that day's copy. A failed fetch
prints a notice and leaves saved data intact. With no saved forecast, the
benchmark is unavailable and the synthetic results still render.

We assume two candidates: `left = (100 + best_bet_margin) / 200` and
`right = 1 - left`. A +6-point margin implies 53% left, 47% Republican.
These are **implied two-candidate forecast shares**, not measured polling shares
or win probabilities. Independent left candidates retain their party category.
Other parties and non-voting are unmeasured, not zero observations.

The same saved daily figures feed the 100-seat headline, response time series
(diamond markers), and 35-state grid. The larger implied share wins the seat;
exact ties stay unallocated. The configured 65-seat baseline remains in use.
Historic dates never borrow a forecast from another day. Daily collection requires
a render or explicit fetch each day; there is no background schedule or verified
historical state API. Forecast data is credited to Polling Forecast, CC BY 4.0.

Fetch without rendering:

```powershell
uv run --offline --frozen python docs/_tools/polling_forecast.py --fetch
```

## The workflow

From the repository root:

```powershell
quarto render docs
uv run python docs/_tools/check_website.py
```

If Quarto is not on PATH on this computer, replace the render command with:

```powershell
& "$env:LOCALAPPDATA\Programs\Quarto\bin\quarto.exe" render docs
```

Rendering automatically fetches the public forecast and then runs the offline
preparation script through Quarto's project `pre-render` hooks. They use the existing uv environment with
`--offline --frozen`; install project dependencies with `uv sync` on a new machine
before building. Rendering never sends model requests.

Preparation checks the saved inputs on each render, but **reuses unchanged
figures**. It renders an SVG only if its relevant data, figure code, or settings
changed, or if the output is missing/edited. New dates create new figure folders
without regenerating archived state/headline figures. Correcting an old observation
updates the current time-series charts because they include history. Prose
or CSS edits do not regenerate SVGs. The disposable cache is stored in the ignored
`docs/.quarto/site-figures.json`; deleting it causes one full rebuild.

The latest reporting day is the greatest parsed ISO date, regardless of directory
listing order or modification time. Each model's Latest view still falls back to
its most recent complete day, labelled with that actual date.

1. Preparation discovers dated folders in `data/llm_responses/`, checks their
   saved results and summaries, and writes dated `data/` and `figures/` plus the
   current page's `components/_generated/`.
2. Quarto reads `index.qmd` and those prepared components to write `index.html`
   here. The document itself does not generate research figures or make API calls.
3. The optional checker verifies the rendered assets and 100-seat totals.
4. Commit/push the refreshed `docs/` folder. In GitHub **Settings > Pages**, select
   **Deploy from a branch**, your branch, and **/docs**. There is no custom publishing
   workflow and no daily collection schedule enabled.

## Where to edit

| File or folder | Purpose |
| --- | --- |
| `index.qmd` | Page content and layout. Temporary Latin: 325 introduction words, 1,500 Methods words, 1,500 Discussion words. Replace directly with your writing. |
| `site-config.yml` | Display models, shapes, study condition, sample, timezone, footer contacts, and fixed-seat baseline with provenance. |
| `styles.css` | Fonts, colours, sizes, spacing, and responsive layout. |
| `assets/site.js` | State, model, and date selectors; loads prepared figures. |
| `_quarto.yml` | Quarto rendering settings; output stays in this folder. |
| `_tools/` | Offline preparation, data checks, SVG generation, and tests. |
| `design/` | Detailed requirements and approved mockup for reference. |
| `references.bib` | Saved CES citation for your later writing. |

`index.html`, `data/`, `figures/`, `components/_generated/`, `site_libs/`, and
`search.json` are generated: edit their sources and rebuild instead of editing
these files. Commit the generated files because branch-based Pages does not run
the preparation or Quarto commands. Keep `.nojekyll` alongside `index.html`.

## Daily discovery and failure rules

Name new query runs with an ISO reporting-date prefix, for example
`2026-10-28-all-models`. Existing `oct-26-all-models` and `oct-27-no-luna`
folders also work; no source folders were renamed. Non-dated pilots such as
`mercury-100` are ignored. Dates are checked against recorded collection times in
**America/Toronto**, never file modification time. An evening October 26 run can
therefore have October 27 UTC timestamps and still belong to October 26.

Only `jev`, `mercury`, and `decider` (displayed as **Perplexity**) are used.
Publication also requires the configured level 9, sentence, role_play, no-news
condition and the original `sample_100` sampled rows. Requested provider model
IDs and returned snapshots are retained, including Mercury's free-to-paid change.

- A state/model/day is eligible only with the correct 100 draw positions and
  respondent IDs, 100 numerically valid responses, and means matching the saved
  summary. No partial averages are displayed and no failed rows are replaced.
- Missing/failed models do not stop the other models. Coverage is shown below
  the time-series chart, and full build notices are in `data/history.json`.
- If several runs exist for one model/day, choose a complete run first, then the
  newest collection time. Never pool runs, take extra draws, or average models.
- Each headline bar uses that model's newest complete **35-state** snapshot and
  shows its date. All 100 seats use solid party colours; baseline and projected
  seats have the same fill. Independents are gray between the parties and remain
  unassigned. Explicit labels distinguish a party lead from a 51-seat majority;
  the bar has no cumulative majority tick. There is no model consensus projection.
- **Latest** in the grid uses each model's newest complete snapshot, with actual
  dates on each row. Choosing a historical date uses only that day's data;
  missing state/model rows say Unavailable, with no silent backfilling.
- Time-series panels retain all 100 sampled rows per eligible model/day and use
  a calendar-date x-axis. Jev is a circle, Mercury a triangle, Perplexity a square.
  Missing days break lines. Jitter is horizontal only; probabilities are unchanged.

Daily data exports, state figures and headline figures are retained:

```text
data/YYYY-MM-DD/snapshot.json             anonymous draws and provenance
figures/YYYY-MM-DD/states/                state shares for that date
figures/YYYY-MM-DD/senate/                each complete model's seat bar
figures/NEWEST-DATE/responses/            current full-history time series
figures/personas/sample_100/              shared fixed-sample CES checks
data/history.json                        browser manifest and selected paths
```

The Latest grid reuses the newest dated state figures when they match. Only when
model dates differ is a separate `states-latest/` folder generated under the
newest date. Validation charts are stored once per persona sample. The page never
needs archived copies of earlier cumulative time-series SVGs: the current figures
contain all dates, and the saved daily data can reproduce previous views.

After a successful preparation, the build removes recognized generated SVGs in
older `responses/` folders and unused `states-latest/` folders. It preserves all
daily data, state/headline archives, unrecognized files, and original analysis
inputs. This implements the approved retention policy without general-purpose
deletion of old folders. The seed label comes from saved persona metadata; seat
counts and explanatory text use the baseline in `site-config.yml`.

To regenerate only data/figures without rendering the page:

```powershell
uv run python docs/_tools/prepare_website.py
```

The Costs section shows running totals per model plus an overall total across
the displayed dates: recorded attempts, input tokens, output tokens, and USD cost.
Raw logs include retries and output tokens; the current Parquet results include
input tokens and costs but no output-token field. If logs are missing, deduplicate
latest results by state/respondent and mark their totals partial because earlier
retries cannot be reconstructed. Unknown fields stay unknown; a greater-than-or-
equal sign marks a known subtotal with missing usage. These totals cover selected
daily runs, excluding non-dated pilots and models outside the configured study.
Duplicate sampled rows are never extra requests or tokens. Headline dates appear
in the shared source note rather than beneath each model name.
Preparation leaves `index.qmd` and its temporary Latin text unchanged.

## Preview and verification

```powershell
uv run python -m http.server 8137 --bind 127.0.0.1 --directory docs
```

Open <http://127.0.0.1:8137/>. Use HTTP so chart selectors can fetch the SVG/JSON
files. Restart an older preview server if it points to another directory.

Run the website's calculation and figure tests separately from the analysis tests:

```powershell
uv run python -m unittest discover -s docs/_tools -p 'test_*.py' -v
```

An optional offline controller test uses Quarto's bundled Deno on this computer:

```powershell
& "$env:LOCALAPPDATA\Programs\Quarto\bin\tools\x86_64\deno.exe" run --no-config --allow-read=docs docs/_tools/test_site_controller.js
```

These checks do not replace reviewing the page in a browser.

The footer shows the contacts from `site-config.yml` and the latest saved model
collection timestamp in America/Toronto, rather than the website render time.
It has no GitHub/source link.

Headline names use each model's `full_name` in `site-config.yml`, followed by the
requested provider ID and returned snapshot from saved results. Short labels
remain in compact charts and controls.
