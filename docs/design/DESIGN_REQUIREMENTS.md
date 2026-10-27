# The Synthetic Electorate: website design and implementation requirements

> Current folder layout (27 October 2026): all website source, rendered output,
> assets, baseline, and Python build tools now live in `docs/`. The build tools
> are in `docs/_tools/`; there is no separate `website/` or `scripts/` folder.
> Use `docs/README.md` for current commands. Older stage examples below describe
> the planned architecture and do not override this consolidation. The site
> now discovers dated three-model runs; see the confirmed update below.

**Document version:** 1.1 — 26 October 2026  
**Status:** Agent handoff specification; confirmed requirements plus explicit implementation defaults and open decisions.  
**Target:** A Quarto website published on GitHub Pages.  
**Visual reference:** [Approved full-page mockup](approved-mockup.png).

## Confirmed headline and cost presentation update

Remove the "Latest eligible" subheading beneath each model. Keep actual model
snapshot dates in a shared source note below the headline results. Costs are
running totals per configured model across the displayed daily runs, with an
overall total row. Include logged attempts, input tokens, output tokens, and USD
cost. Raw attempt logs supply complete recorded usage when available; deduplicate
Parquet results by state/respondent as a partial fallback. Never multiply usage by
persona draw multiplicity or convert missing tokens/cost into zero. Mark known
subtotals when usage is incomplete. This supersedes per-day cost-table defaults.

## Confirmed headline clarification

Keep independents unassigned to either party and show their gray segment between
Democrats and Republicans. Add a model-specific result label: a party with 51+
seats has an outright majority; D50/R48/I2 is "Democrats lead; no outright majority."
Remove the cumulative vertical 51-seat marker, which misleadingly fell inside
red even when Republicans had fewer seats. State the 51-seat threshold as shared
explanatory text. Party counts remain unchanged and separate. This supersedes
older reference-marker requirements below.

## Approved simplification of generated outputs

Store the fixed-seat baseline and provenance in `docs/site-config.yml` alongside
website settings. Read the seed from saved persona metadata. Export CES validation
charts once per sample under `figures/personas/<sample>/`. Retain dated state and
headline figures plus all daily data. Retain cumulative response SVGs only under
the newest reporting date; they contain the full history. Reuse the dated state
grid for Latest when it matches, generating a mixed-date grid only when needed.
Superseded generated cumulative/current-grid SVGs are pruned; original run data
and daily state/headline archives are preserved. These approved rules supersede
older examples that duplicate every chart for every date.

## Confirmed owner update: dated three-model website

These decisions supersede conflicting defaults and earlier open questions below:

- Display Jev (`jev`), Mercury (`mercury`), and Perplexity (`decider`), with one
  independent headline seat bar per model. No consensus average.
- Headline party segments use solid `#326A9D`, `#BD4942`, and `#777777` fills.
  Fixed and contested seats have identical colours; retain the 51-seat marker.
- Discover reporting dates from ISO run prefixes, supporting the existing legacy
  month/day prefixes and validating against America/Toronto timestamps.
- Require the original 100 sampled rows and 100 valid responses per state/model/day.
  Missing/failed models leave gaps and never prevent other models from publishing.
- Headline and Latest overview use each model's newest complete 35-state day,
  with explicit dates. Historical selections never borrow an earlier day's data.
- Time series show all observed days and all sampled rows, with stable shapes:
  Jev circle, Mercury triangle, Perplexity square. Only state/model selection is
  interactive here. The grid's date selector remains independent.
- Save generated model data and figures under date-labelled folders in `docs/`.
  The normal Quarto render invokes a separate offline Python preparation script.
- For layout review, use Latin text: approximately 325 introduction words,
  1,500 Methods words, and 1,500 Discussion words. This replaces the earlier
  request for empty Methods/Discussion. Owner writing will replace it later.
- Current settings and build commands are documented in `docs/README.md` and
  `docs/site-config.yml`; third-party data and daily API scheduling remain unimplemented.

## Contents

1. [How to use this document](#1-how-to-use-this-document)
2. [Project purpose and confirmed decisions](#2-project-purpose-and-confirmed-decisions)
3. [Open decision register](#3-decision-register-ask-before-filling-these-in)
4. [Page map and anchors](#4-page-map-reading-order-and-anchors)
5. [Visual system and CSS tokens](#5-visual-system-and-css-tokens)
6. [Responsive layout and above the fold](#6-responsive-layout-and-above-the-fold-requirement)
7. [Masthead and introduction](#7-masthead-introduction-and-editorial-identity)
8. [Headline Senate results](#8-latest-headline-senate-results)
9. [Detailed state time series and polling](#9-detailed-state-time-series)
10. [All-model state overview](#10-across-the-states-all-models-selected-date)
11. [Methods and persona validation](#11-methods-and-persona-validation)
12. [Discussion, costs, and footer](#12-discussion-costs-and-footer)
13. [Data contracts](#13-data-meaning-normalization-and-contracts)
14. [Interaction ownership](#14-interaction-ownership-and-section-independence)
15. [Freshness and history](#15-freshness-history-and-publication-behaviour)
16. [Actions and Quarto architecture](#16-github-actions-and-quarto-architecture)
17. [Failure states](#17-failure-states-and-reader-facing-messages)
18. [Accessibility](#18-accessibility-and-usable-chart-behaviour)
19. [Performance](#19-performance-and-data-loading)
20. [Agent work boundaries](#20-suggested-filecomponent-boundaries-for-different-agents)
21. [Known-answer fixtures](#21-test-fixtures-and-mathematical-examples)
22. [Acceptance checklist](#22-acceptance-and-review-checklist)
23. [Decision history](#23-decision-history-and-superseded-mockup-details)
24. [References](#24-references-for-implementing-agents)

## 1. How to use this document

This document is intended to be passed to a designer, frontend agent, data agent,
automation agent, or reviewer without requiring access to the original chat.
Read sections 2–4 before starting work, then the relevant component and data
sections. Use the acceptance criteria in section 22 when handing work back.

Requirement identifiers such as `HEAD-01` are stable references for issues,
implementation notes, and review comments. Refer to identifiers when explaining
what a change implements. Do not silently replace an unresolved methodological
choice with an implementation convenience.

### 1.1 Requirement status and authority

| Status | Meaning | What an implementing agent may do |
| --- | --- | --- |
| **CONFIRMED** | Explicitly requested or clarified by the project owner. | Implement as written. Ask before changing it. |
| **DEFAULT** | A concrete implementation choice supplied to make the approved design buildable. It has not been individually approved by the owner. | Use for the MVP; report material deviations. Routine CSS adjustments do not require a new approval round. |
| **OPEN** | Information or a substantive decision has not been supplied. | Build the surrounding structure with an explicit unavailable state. Ask the owner before supplying real values or enabling dependent behaviour. |

The latest explicit owner clarification takes precedence over an older mockup or
requirement. Within this document, confirmed behavioural requirements take
precedence over incidental details in the reference image.

The reference is an AI-generated design image, not a source of election data.
Do not copy its example percentages, 48/52 or 49/51 seat counts, invented history,
imperfect tick labels, or other incidental rendering errors into production.

### 1.2 Deliverable boundary

This specification defines the website and its supporting data/update contracts.
It does not itself authorize a paid model run or a deployment. Creating this
document has not created a Quarto implementation, enabled Actions, or connected
an external data feed. Implementation work should preserve existing analysis
scripts and data unless that implementation task explicitly requires a change.

## 2. Project purpose and confirmed decisions

The website presents synthetic Senate-election responses generated by language
models using personas sampled from the Cooperative Election Study (CES). It
must make the synthetic nature of the results obvious before a reader sees the
headline numbers. It is a research publication, with an original newspaper-like
identity, rather than a conventional application dashboard.

| ID | Confirmed requirement |
| --- | --- |
| `CORE-01` | Use Quarto, with GitHub Pages as the intended hosting platform. |
| `CORE-02` | Retain the approved editorial/newspaper appearance, original masthead, restrained party colours, thin rules, and clear chart hierarchy. |
| `CORE-03` | Put the introduction above the first headline result. Keep it compact enough that headline results remain prominent above the fold. |
| `CORE-04` | Show the latest model-implied Senate seat results using a precomputed baseline for 65 seats and projections for the 35 contested seats. |
| `CORE-05` | The owner will specify which models appear in the headline. Do not infer that list from whichever models currently have files. |
| `CORE-06` | Determine a state's winning category from the largest average probability among Democrat, Republican, and Third party, even if that average is below 50%. Exclude Would not vote from the winner comparison. |
| `CORE-07` | Show projected independent/third-party seats in grey, consistent with the state-by-state category colour. Do not force these seats into Democrat or Republican totals. |
| `CORE-08` | The time-series section permits selection of state and a subset of models. Those are its only selection controls. |
| `CORE-09` | Show variation from all 100 sampled persona rows for each model/state/day in normal complete runs, using different light marker shapes for different models. |
| `CORE-10` | Overlay compatible third-party polling directly on the relevant time-series plots. Do not restore the removed External benchmarks section. |
| `CORE-11` | Show all models in the 35-state overview, not merely the headline subset or the models selected in the time-series section. |
| `CORE-12` | The 35-state overview permits selection of Latest or an available earlier date. It does not have a model-selection control. |
| `CORE-13` | The persona-match section includes every feature tested in the relevant saved persona-validation outputs. |
| `CORE-14` | Query the chosen models DAILY. This supersedes the earlier every-two-days proposal and the cadence text in the mockup. |
| `CORE-15` | Use the freshest available results for latest views and archived past results for time series. Never fabricate historical observations. |
| `CORE-16` | Include a compact Polymarket winning-odds chart directly below the four response panels, inside the existing time-series section. It follows the selected state and shared date axis, adds no controls, and does not change the headline. |
| `CORE-17` | Keep Methods, Discussion, and Costs sections below the results, with persona-validation charts following Methods. |

### 2.1 Important clarifications from the owner

* The winner rule is a **plurality of averaged response probabilities**, not a
  requirement to exceed 50%, and not a count of personas' highest-ranked choices.
* The time-series cloud is based on the **100 sampled rows**, not only the unique
  CES respondent IDs that were queried. Repeated respondent draws remain rows.
* Model lists and prompt settings are still to be decided. The architecture must
  support different daily-query, headline, and time-series-selection lists.
* The state overview shows **all models** in the configured study. Filtering the
  detailed time-series model list must not filter the state overview.
* The owner approved a compact Polymarket winning-odds companion chart after
  initially deferring the display decision. Its winning odds remain separate
  from vote-intention polling percentages and the four model-response panels.

## 3. Decision register: ask before filling these in

An OPEN item does not block layout development or fixture-based tests. It blocks
claiming a real data integration, a real model comparison, or a live scheduled
experiment that depends on that answer. Keep unresolved configuration values
explicit rather than choosing a convenient model, source, or price.

| ID | Open decision | What is already fixed | Dependent work |
| --- | --- | --- | --- |
| `OPEN-01` | Exact daily model keys and pinned provider model IDs. | Support multiple models; run the selected study models daily. | Live query configuration and model availability. |
| `OPEN-02` | Headline model subset, order, and default selected time-series subset. | Headline is owner-prespecified; overview shows all study models; time series allows a subset. | Real default model displays. |
| `OPEN-03` | Persona level, sentence/list format, prompt style, and optional experimental conditions. | Keep those settings explicit and separate; do not blend different configurations. | Comparable model groups and historical series identity. |
| `OPEN-04` | Vote-intention polling provider, endpoint/data format, population, category definitions, and reuse permission. | Polling belongs on the existing time-series plots where comparable. | Polling adapter and real overlays. |
| `OPEN-05` | Verified Polymarket contracts/outcomes, state coverage, and price-source convention. | Compact state-linked odds chart approved; no separate External benchmarks section or headline market row. | Real market mapping, quote provenance, and coverage checks. |
| `OPEN-06` | Whether daily model calls use unchanged prompts or dated news/context, and which context source. | Daily acquisition is required. | Interpretation of temporal changes and context ingestion. |
| `OPEN-07` (resolved for MVP) | Owner supplied 32 Democratic, 31 Republican, 2 independent fixed seats on 26 October 2026. Saved in `docs/site-config.yml (baseline section)`. | Add the 35 modeled winners; keep independents grey and separate. | Baseline implemented; individual seat provenance remains a later enhancement. |
| `OPEN-08` | Daily collection time, reporting-day timezone, and external-feed refresh frequency. | Model calls are daily; stored timestamps must be explicit. | Actions schedule and canonical daily cutoffs. |
| `OPEN-09` | API spending limits and how missing provider cost values should be reconciled. | Include all attempts; do not count expanded duplicate rows as separate calls. | Paid automation and complete cost reporting. |
| `OPEN-10` | Repository/Pages destination, deployment permissions, and durable archive location. | Quarto + GitHub Pages; past observations must survive the runner. | Actual deployment and production persistence. |
| `OPEN-11` | Whether partial-but-numerically-valid snapshots may update headline seat counts. | Exclusions must remain visible; never treat a missing state as a loss or an independent win. | Publication quality threshold. |

**Owner questions to carry into the next implementation discussion:** model and
prompt lists (`OPEN-01`–`03`), polling/context sources (`OPEN-04`–`06`), verified
baseline (`OPEN-07`), and operational settings (`OPEN-08`–`11`). The owner has
already said the model lists are undecided; do not keep asking those same
questions unless implementation actually needs the answer. Polymarket's compact
chart placement is now resolved; do not reopen that design decision.

## 4. Page map, reading order, and anchors

`PAGE-01` — Build one continuous editorial landing page with this exact order.

| Order | Anchor | Component | Content |
| --- | --- | --- | --- |
| 1 | Page top | Edition line and masthead | Original project identity and 2026 Senate research context. |
| 2 | Navigation | Section links | Results, Introduction, Methods, Discussion, Costs. |
| 3 | `introduction` | Synthetic label and introduction | Research question, CES personas, synthetic responses. |
| 4 | `results` | Latest headline seat graphic | Owner-selected models, fixed baseline, projected contested seats, as-of labels. |
| 5 | `responses-over-time` | State detail/time series | State/model selectors, four response panels with polling overlays, followed by one compact Polymarket winning-odds chart. |
| 6 | `across-the-states` | 35-state grid | All study models; Latest/historical date selector. |
| 7 | `methods` | Methods | Sampling, models/prompts, validation, aggregation, daily update process. |
| 8 | `persona-validation` | Persona matching | All validated features for a selected state. |
| 9 | `discussion` | Discussion | Interpretation, limitations, model differences, external comparisons. |
| 10 | `costs` | Cost accounting | Model-level attempt counts and actual recorded costs. |
| 11 | Footer | Project/source links | Methods/source code link and concise attribution. |

`PAGE-02` — Navigation links scroll to their named sections. Navigation order
may remain as in the mockup even though Introduction physically precedes Results.
Use real anchors so links work without a JavaScript application router.

`PAGE-03` — Do not add a sidebar, a separate dashboard landing page, an External
benchmarks block, or extra filter panels. Quarto's automatic table of contents,
default sidebar, theme navbar, and default title block must not create duplicate
navigation or push the approved masthead below an extra header.

`PAGE-04` — No global model/date control. Each selector has an explicitly scoped
effect, defined in section 14. In particular, the global snapshot/model controls
depicted in the older mockup are superseded by the owner's latest control rules.

## 5. Visual system and CSS tokens

**Status:** DEFAULT values translating the confirmed visual direction into
implementable measurements. Use one shared stylesheet/token source. Do not let
each chart agent invent a slightly different palette, font scale, or divider.

### 5.1 Colour tokens

| Token | Value | Use |
| --- | --- | --- |
| `--paper` | `#FAF9F6` | Page and chart plotting background. |
| `--ink` | `#181817` | Main text, strong rules, axis text. |
| `--muted-ink` | `#62615D` | Captions, secondary metadata, supporting labels. |
| `--rule` | `#D9D6CE` | Grid separators, subtle section rules. |
| `--strong-rule` | `#242422` | Major editorial separators. |
| `--democrat` | `#326A9D` | Democratic probability/seat category. |
| `--republican` | `#BD4942` | Republican probability/seat category. |
| `--third-party` | `#777777` | Third-party/independent probability and seat category. |
| `--non-vote` | `#C7C7C3` | Would-not-vote probability category only. |
| `--polling` | `#252525` | External vote-intention polling line/markers. |
| `--focus` | `#125B88` | Clearly visible keyboard-focus outline. |

`STYLE-01` — Colour represents political response category. Model identity is
primarily line style and marker shape. Do not reuse a party colour to mean a
different party merely because another model is selected.

`STYLE-02` — Use dark labels outside light grey marks. Light grey is not an
acceptable body-text colour. Distinguish an unavailable/unallocated seat by an
outline or hatch, not the same filled grey used for independent seats.

`STYLE-03` — Use no gradients, rounded dashboard cards, large shadows, glossy
controls, decorative stock imagery, or unrelated accent palette. The approved
newspaper effect comes from type hierarchy, spacing, rules, and chart precision.

### 5.2 Typography

| Token/component | Desktop | Mobile | Notes |
| --- | --- | --- | --- |
| Display family | `Georgia, "Times New Roman", serif` | Same | DEFAULT system-font MVP; avoid a required external font request. |
| Body family | `Georgia, "Times New Roman", serif` | Same | Narrative sections. |
| Chart/control family | `system-ui, -apple-system, "Segoe UI", sans-serif` | Same | Labels, dates, controls, tables. |
| Masthead | 64px / 1.02, bold | 36px / 1.05 | Centred, original title. |
| Lead headline | 48px / 1.08, bold | 30px / 1.12 | Centred over seat chart. |
| Section heading | 32px / 1.15, bold | 25px / 1.2 | Left aligned except the lead result. |
| Narrative body | 18px / 1.55 | 17px / 1.55 | Target 60–75 characters per prose line. |
| State heading | 16px / 1.2, bold | 16px / 1.2 | Never truncate state names. |
| Caption | 13px / 1.45 | 13px / 1.45 | Muted dark grey. |
| Chart labels | 12–14px / 1.3 | At least 12px | Small grid model labels may be 12px. |
| Controls | 14px | 16px | Mobile input size prevents browser auto-zoom. |
| Seat counts | 48px / 1, bold | 36px / 1 | Number must be visually dominant. |

`STYLE-04` — Use tabular numerals for percentages, dates where applicable, seat
counts, and costs. Keep consistent precision across comparable entries. Final
copy may use curly punctuation, but technical variable names remain literal.

### 5.3 Spacing, borders, and alignment

| Property | DEFAULT |
| --- | --- |
| Content max-width | 1,240px, centred. |
| Page side padding | 32px desktop; 24px tablet; 16px phone. |
| Spacing scale | 4, 8, 12, 16, 24, 32, 48, 64px. |
| Major section separation | 48px including rule/padding; 32px on phones. |
| Related heading-to-chart gap | 12–16px. |
| Grid gap | 20px horizontal; 16px vertical. |
| Thin rule | 1px. |
| Strong section rule | 2px maximum. |
| Masthead separator | Restrained double rule, following the mockup. |
| Control corner radius | 0–2px; no pill controls. |

`STYLE-05` — Align outer edges of the masthead rules, hero, detail charts,
overview grid, and major prose sections to the same content container. Prose
may use internal columns; do not give every section a different outer width.

## 6. Responsive layout and above-the-fold requirement

| Viewport width | State grid | Time-series panels | Persona-validation charts | Narrative layout |
| --- | --- | --- | --- | --- |
| At least 1,200px | 5 columns | 2 columns | 3 columns | Two prose columns where useful. |
| 900–1,199px | 3 columns | 2 columns | 2 columns | One or two according to line length. |
| 768–899px | 3 columns | 1 column | 2 columns | One prose column. |
| 480–767px | 2 columns | 1 column | 1 column | One prose column. |
| Below 480px | 1 column | 1 column | 1 column | One prose column. |

`LAYOUT-01` — At 1440 × 900 with two headline models, show the masthead,
navigation, synthetic label, short introduction, headline title, and both seat
rows without requiring a scroll. Target their combined height at 820px or less.
When the owner chooses more headline models, preserve readable row sizes; do
not shrink all typography to force an arbitrary count above the fold.

`LAYOUT-02` — Reflow; do not scale a desktop screenshot to phone width. The
reference image is not an asset to use as the website itself.

`LAYOUT-03` — No page-wide horizontal overflow at 360px width. Tables may use a
contained horizontal scroll region when necessary. Charts must resize to their
container and retain labels and accessible values.

`LAYOUT-04` — DEFAULT detailed plot height is 240px per panel on desktop and
250px on phones, excluding its heading/legend. The four panels share aligned
plot areas. Increase validation plot height for long category lists rather than
cutting labels or shrinking text below the specified minimum.

The Polymarket companion chart is additional to those four panels: DEFAULT height
160px desktop and 180px mobile, excluding its compact heading and caption. It
spans the detail section's full width beneath the two-column response grid.

## 7. Masthead, introduction, and editorial identity

`INTRO-01` — DEFAULT project title: **The Synthetic Electorate**, as approved
visually. Use an original masthead; do not reproduce a New York Times logo.

`INTRO-02` — Above the masthead use a small edition line, such as “Research
edition” on the left and “2026 U.S. Senate” on the right. These are contextual
labels, not additional navigation.

`INTRO-03` — Place **SILICON SAMPLING · SYNTHETIC RESULTS** before the headline.
The explanatory introduction must state that model responses are synthetic and
that personas preserve characteristics from sampled CES respondents. CES means
**Cooperative Election Study**, not Current Employment Statistics.

`INTRO-04` — DEFAULT introductory copy, subject to editorial revision:

> We ask language models how sampled respondents from the Cooperative Election
> Study (CES) might vote. Responses are synthetic; personas preserve recorded
> CES characteristics.

Keep this to roughly 45–75 words in production. Methods belongs lower down;
the introduction should not become a long literature review above the results.

## 8. Latest headline Senate results

### 8.1 Fixed behaviour

`HEAD-01` — The heading is “Who would control the Senate?” or owner-approved
equivalent. Follow it with a precise description such as “Model-implied seat
projection.” Never label mean response shares as calibrated win probabilities.

`HEAD-02` — Render one row for each model in the owner-specified `headline_models`
list, in that list's order. No headline model selector, date selector, polling
toggle, or time-series selection may change these rows.

`HEAD-03` — Each row uses that model's freshest publishable result for the exact
configured experimental condition. Display the observation date/time per row if
models differ in freshness. Do not silently fall back to a common old date just
to make rows look aligned, or silently mix states from different model snapshots.
The publication threshold for partial snapshots is `OPEN-11`.

`HEAD-04` — If a specified model has no eligible result, retain its labelled row
with “Results not yet available.” Do not substitute another model or an invented
value. Do not use the mockup's sample seat counts.

### 8.2 Fixed baseline and winner calculation

`HEAD-05` — Precompute and verify the 65 non-contested seats once for this
election configuration. Keep this baseline separate from model outputs. Query
neither personas nor models to estimate those seats.

`HEAD-06` — The baseline should preserve individual seat identities, party,
independent status, class/state, source, and as-of date, then aggregate to
Democrat, Republican, and Independent/other categories. Do not merge independent
seats into a major party without an explicit later instruction.

`HEAD-07` — For each contested state/model, obtain the three valid state means:

```text
winner = argmax(mean_p_democrat, mean_p_republican, mean_p_third_party)
```

Exclude `mean_p_would_not_vote`. A state with D=0.44, R=0.42, Third=0.04,
Non-vote=0.10 is allocated to D. A state with D=0.30, R=0.25, Third=0.35,
Non-vote=0.10 is allocated to the grey Independent/other category. Do not count
each persona's argmax as a ballot: that is a different estimator.

The model's Third party option represents an independent **or other party**.
The grey seat is therefore a model-implied non-major-party category, not proof
that a named independent candidate would win. Explain this limitation in Methods.

`HEAD-08` — DEFAULT tie handling: compare full-precision means before rounding;
differences no larger than `1e-12` count as tied for allocation. Leave ties and
missing state results **unallocated**, represented by a neutral outline/hatch.
Never resolve a tie alphabetically or treat an unavailable state as independent.

`HEAD-09` — Compute totals for every displayed model independently:

```text
party_total = fixed_baseline_party_seats + contested_seats_won_by_party
sum(fixed_baseline seats) = 65
resolved_contested + unallocated_contested = 35
D_total + R_total + Independent_other_total + unallocated = 100
```

The 35-state set is defined in section 10. Use seat/race identifiers in the
underlying baseline rather than assuming that a state can never have two Senate
contests in another election cycle.

### 8.3 Graphic specification

`HEAD-10` — Use a 100-seat horizontal bar for every model, aligned to the same
width. Show blue Democratic, red Republican, and grey Independent/other segments
where nonzero. Unallocated seats need a distinct outline/hatch, not filled grey.
Non-voting responses do not create a Senate seat category.

`HEAD-11` — Show large party seat totals and the model name. When an independent
segment exists, provide its count and label without hiding it to preserve a
two-party layout. Use a clear 51/100 reference marker labelled “51 for an
outright majority.” Do not assume a 50–50 split automatically establishes control.

`HEAD-12` — DEFAULT bar height: 24px desktop, 20px mobile. Model rows have at
least 20px separation. Use solid party fills with no baseline/projected shading,
per the confirmed owner update. Party labels/counts must remain explicit.

## 9. Detailed state time series

### 9.1 Allowed controls and defaults

`TIME-01` — This section is titled “How simulated responses change over time.”
It contains exactly two kinds of selection control: a state dropdown and model
checkboxes. The model control allows any subset of configured published models.

`TIME-02` — DEFAULT initial state is Georgia, matching the reference. Default
selected models are owner-configured (`OPEN-02`), not hardcoded to Mercury/Jev.
If none is selected, show “Select at least one model” without changing another
section's results. All supported states remain available even if some have no
data for a chosen model.

`TIME-03` — Do not add a date slider, range picker, latest/history toggle,
polling-source selector, comparison toggle, prompt-setting selector, zoom/pan
controls, lasso, or chart export toolbar. In particular, remove “Compare with
polling” and “View: Latest | Over time” controls from the mockup implementation.

`TIME-04` — Hover/focus tooltips are informational and permitted. Legends do not
toggle traces; the model checkboxes are the single model-selection mechanism.
Disable plot drag/scroll zoom and double-click rescaling. Keep the graph frame
stable when a model selection changes.

### 9.2 Panels, axes, and model identity

`TIME-05` — Always show four panels in this order: Democrat, Republican,
Third party, Would not vote. Use one 2 × 2 panel group on wide screens and stack
in that order on narrow screens.

`TIME-06` — Use calendar date on x and probability on y. All four panels use
0–100% and the same x domain for the selected state. Show actual recorded daily
observations. Connecting adjacent observations is allowed, but do not create
interpolated daily points or render a missing day as an observed zero.

`TIME-07` — Category colour remains blue/red/charcoal/light grey. Assign each
model a stable marker shape and mean-line style. DEFAULT first shapes are circle,
triangle, square, and cross; reserve diamonds for polling. Model assignments
must not change when another model is deselected. Support at least four models
without relying on colour alone. Larger lists must wrap the legend cleanly.

### 9.3 Persona clouds: all 100 sampled rows

`TIME-08` — For a complete model/state/day with 100 draws, draw **100 light
persona markers in each probability panel**. This is 100 sampled rows, including
repeated CES respondents. Do not reduce the cloud to unique queried IDs. A daily
two-model state has 200 persona markers per panel, plus mean/poll markers.

`TIME-09` — Model cloud markers use that model's shape, with category-coloured
fill/stroke and roughly 0.12–0.20 opacity. DEFAULT marker size is 3–4px. Mean
markers use the same model identity at 6–7px, strong opacity, and 2px lines.
Keep faint clouds visually subordinate to the means and polling overlay.

`TIME-10` — Repeated rows can have exactly the same probability because one
unique respondent response is reused. Use small deterministic **horizontal-only**
jitter to expose overlap. Do not jitter y values or imply that jittered x values
are actual intraday timestamps. Tooltips show the actual snapshot date. Use the
same row-level jitter across categories where possible.

`TIME-11` — Invalid/refused/failed rows do not receive invented numeric dots.
Show the actual valid count versus expected 100 in the mean tooltip and expose
an incomplete-data note when necessary. The data layer must retain the expected
row count even when fewer valid probability markers can be drawn.

`TIME-12` — Calculate each mean from valid sampled rows, preserving multiplicity:

```text
mean(category) = sum(valid sampled-row probabilities for category) / n_valid
```

For an equivalent unique-respondent table, multiply by the respondent's draw
count and divide by the sum of valid draw counts. Do not apply CES commonweight
again. Do not average unique respondents equally when they have unequal draw
multiplicities, and do not average model means into an unrequested consensus.

`TIME-13` — Persona tooltip: model, state, date, sampled-row identifier,
probability, and indication that repeated draws may share a queried response.
Use a stable site-local identifier rather than exposing raw CES case IDs by
default. Mean tooltip: model/version, actual snapshot timestamp, mean, n_valid,
n_expected, unique respondent count, and exclusion count where available.

`TIME-14` — Required explanatory caption:

> Dots show variation among sampled personas, not a confidence interval. Lines
> show average model responses across the sampled draws, including repeated draws.

Do not label this cloud “margin of error,” “95% confidence,” or “probability the
party wins.” A separate uncertainty-estimation method would require new approval.

### 9.4 Vote-intention polling overlays

`POLL-01` — Compatible third-party vote-intention data is drawn directly on the
existing category panels. Use the near-black dash-dot line and diamond markers,
with an explicit “Polling average” or provider-specific legend label.

`POLL-02` — Overlay only documented comparable categories/populations. Record
whether respondents are adults, registered voters, or likely voters; poll
fieldwork dates; release date; sample size where supplied; and undecided/non-vote
treatment. Do not automatically renormalize the model's four categories to
match a poll's two-category denominator.

`POLL-03` — “Freshest polling” means the freshest available observation with
its source/fieldwork date shown, not a promise that a new poll exists every day.
Never invent daily polls, a Third party series, or a Would not vote series. A
series not supplied by a comparable source is absent with a small availability
note. Any carried-forward external value must be explicitly identified as such.

`POLL-04` — Polling tooltips identify the provider and original observation
date, rather than presenting the fetch timestamp as the poll date. If an average
is computed from polls, its construction and date window must be documented.

`POLL-05` — Polymarket must be representable as an external-data source option,
with contract/outcome identifiers, observation times, and source metadata.
A market price is a winning-odds measure, not the category response share shown
on the four panels. Display it only in the compact companion chart specified
below. Do not overlay it on the response-share axes, add a dual axis, restore an
External benchmarks section, or insert a market-based headline row.

### 9.5 Compact Polymarket winning-odds chart

`ODDS-01` — Place one chart immediately below the four response panels and their
persona-variation caption, before “Across the states.” Keep it within the same
`responses-over-time` section; it is not a separate benchmarks section or a
fifth response category. Its heading is **“Polymarket: chance of winning.”**

`ODDS-02` — The existing time-series state dropdown updates this chart together
with the four model-response panels. Add no market dropdown, date picker,
on/off toggle, source selector, or other selection control. The model checkboxes
affect model traces only; deselecting a model does not alter market prices or
hide the Polymarket chart. The chart may remain visible when no model is selected.

`ODDS-03` — Use the same displayed calendar-date domain as the response panels,
with its own y-axis labelled **“Market-implied chance of winning”**, spanning
0–100%. Use 0%, 50%, and 100% ticks and restrained gridlines. Model selection
must not rescale the shared time window. Comparison points use consistent daily
cutoffs; retain actual observation timestamps rather than implying simultaneous
collection or filling missing dates with invented prices.

`ODDS-04` — Show verified Democratic, Republican, and independent/other outcome
series where available. Use the established category colours, a compact shared
legend, and small diamond markers at recorded comparison observations. No model
mean lines or persona clouds belong in this chart. A “Would not vote” series is
not a Senate-election winning outcome and must not be synthesized.

`ODDS-05` — Map each state/race to a reviewed **general-election winner** market,
including its actual resolution rules. Do not substitute a primary winner,
first-round-only outcome, chamber-control market, or margin-of-victory bucket.
Named-candidate outcomes need an explicit party mapping. If several candidates
would be grouped as Other, require verified mutually exclusive outcomes and a
documented aggregation rule; otherwise label individual available outcomes or
leave the grouped series unavailable. Never infer R=1-D when other outcomes or
contract definitions make that inference unsupported.

`ODDS-06` — A tooltip/focus equivalent identifies state/race, candidate/party,
market/outcome, price as a percentage, actual observation timestamp, and price
basis where known (e.g. midpoint, last trade, or API historical observation).
Provide a small source link and actual as-of label. Preserve bid/ask or available
liquidity metadata for quality checks; stale or sparse observations must not be
presented as fresh, precise polling measurements.

`ODDS-07` — Retain a concise caption:

> Market-implied winning odds, not vote shares. Source: Polymarket.

This chart compares movement over time alongside the models; it does not turn
persona means into calibrated election win probabilities. Do not calculate a
model-minus-market “error,” average their percentages together, or feed market
prices into the LLM prompts as part of this integration.

`ODDS-08` — If no reviewed market, outcome, or history exists, keep a compact
message such as “Polymarket data unavailable for this state/date.” Keep the model
charts functional. Do not hide an unavailable state, manufacture Third party
coverage, insert zeros, or silently borrow another race's data. Preserve all
real historical observations already archived when a later fetch fails.

`ODDS-09` — Discover/review contracts once and persist their identifiers and
metadata. Fetch outcome history through the documented API in the acquisition
pipeline, then archive it by observation time. For daily LLM alignment, use an
observation at or before the chosen cutoff, with an explicit staleness limit;
do not select a future quote because it is closer. Until cutoff/quality settings
are finalized, retain raw timestamps and expose unavailable matches rather than
inventing a tolerance. The public page reads archived static data.

`ODDS-10` — Apply finite inclusive [0,1] checks to individual prices, but do not
apply the LLM vector's strict sum-to-one test to separately quoted market tokens.
Prices may have spreads or asynchronous observations. Preserve their actual
values and provenance; do not blindly normalize them to make displayed outcomes
sum to exactly 100%. Actual 35-state coverage remains to be audited.

## 10. Across the states: all models, selected date

`GRID-01` — Render all 35 state panels, each showing **all study models** in a
configured, consistent order. A model not chosen for the headline still appears
here. A time-series checkbox must never hide its bars from this grid.

`GRID-02` — The only selection control here is one date dropdown with “Latest”
and available historical reporting dates, newest first. Remove the mockup's
“Latest shares | Trends” switch. Changing the date updates all 35 panels together
and affects no other section.

`GRID-03` — Latest uses each model's freshest eligible snapshot, labelled with
its actual date if freshness differs. An explicitly selected historical date
uses that date's archived results only. If a model is missing for that date,
show an unavailable row; do not silently borrow another day's values.

`GRID-04` — Each state panel has a serif heading and one horizontal four-category
stacked bar per model. Label the model row clearly; abbreviations require a
visible full-name key. Shares retain the four original categories, including
Would not vote. Do not substitute the winning-seat category or a two-party share.

`GRID-05` — Use consistent 0–100% scales and category order. DEFAULT bar height
is 10px with at least 6px between rows. Panel height grows with the number of
models; no agent may assume exactly two rows or hide extra models to retain the
mockup's height. Align model rows across neighbouring panels.

`GRID-06` — Use fine separators and whitespace, not raised cards. Show the
category legend once above the grid. Detailed values may be supplied on hover
and in accessible text; do not cram four tiny percentages into every bar.

`GRID-07` — Fixed alphabetical state order (the source set is
`SENATE_STATES_2026` in `src/create_personas.py`):

| Desktop row | Column 1 | Column 2 | Column 3 | Column 4 | Column 5 |
| --- | --- | --- | --- | --- | --- |
| 1 | Alabama | Alaska | Arkansas | Colorado | Delaware |
| 2 | Florida | Georgia | Idaho | Illinois | Iowa |
| 3 | Kansas | Kentucky | Louisiana | Maine | Massachusetts |
| 4 | Michigan | Minnesota | Mississippi | Montana | Nebraska |
| 5 | New Hampshire | New Jersey | New Mexico | North Carolina | Ohio |
| 6 | Oklahoma | Oregon | Rhode Island | South Carolina | South Dakota |
| 7 | Tennessee | Texas | Virginia | West Virginia | Wyoming |

Responsive layouts preserve this reading order. Do not replace this grid with a
map, a sortable ranking, or a dropdown showing one state at a time.

## 11. Methods and persona validation

### 11.1 Methods content

**Owner layout override:** Use approximately 1,500 words of temporary Latin in
Methods until the owner replaces it with their prose in `index.qmd`.
The following items are guidance for that future writing, not instructions to
generate placeholder or explanatory copy during website builds.

`METHOD-01` — Explain the implemented process in plain language: weighted CES
source within each state; sampling with replacement; fixed sample across dates;
persona characteristic selection/formatting; model configurations; four response
probabilities; numerical validation; bounded retries; row-level state averages;
seat allocation; and daily snapshots/archiving.

`METHOD-02` — A compact process diagram may read:

```text
Fixed CES persona sample -> Daily model queries -> Response validation
    -> State means -> Seat allocation and archived snapshots
```

Do not claim a dated-news step until `OPEN-06` is resolved and implemented.
Record the model/version, prompt settings, persona sample identity, seed, and
whether external context was supplied. Do not describe daily reruns of unchanged
prompts as demonstrated changes in real voters' opinions.

`METHOD-03` — Explain that matching weighted state CES does not prove matching
the true state population or likely electorate. Explain that source weights
determine draws and that drawn rows are equally weighted afterward. Age is a
validation feature even though it is not currently in the configured prompt
levels. Keep held-out outcomes out of model prompts.

### 11.2 Required validation features and categories

`VALID-01` — Read feature coverage from the saved validation output for the
actual persona sample. Never hardcode only the mockup's Age/Race/Education trio.
At the time this document was written, all three saved 25/50/100 runs contain:

| Display heading | Feature name | Source field | Specific requirements |
| --- | --- | --- | --- |
| Age | `age` | `birthyr` | Reference year 2025; current bins 18–29, 30–44, 45–64, 65–120; retain configured special categories. |
| Race | `race` | `race` | Preserve the labels/categories in the validation table. |
| Party identification | `pid7` | `pid7` | Preserve detailed categories, uncertainty responses, and missing-response groups. |
| Sexual orientation | `sexuality` | `sexuality` | Preserve refusal/other categories according to validation output. |
| Education | `educ` | `educ` | Preserve the actual education categories; do not replace with the mockup's collapsed groups. |

If another run validates more fields, show those fields too. The current defaults
are in `config/persona_validation.yaml`; CLI overrides can differ, so saved output
coverage determines what a particular comparison actually tested.

`VALID-02` — Provide one state dropdown local to this section. DEFAULT state is
Alabama. Changing it updates every validation feature plot together. It does not
change the detailed time-series state or the 35-state overview date.

`VALID-03` — For each feature use paired horizontal category bars: persona draws
in blue and weighted CES reference in dark charcoal. Use one shared legend and
the same percentage scale. Show both values and their percentage-point difference
on hover/focus. Category labels must wrap or receive more space, never disappear.

`VALID-04` — Preserve all categories in the validation output, including absent,
No response, invalid-age, and unknown-code categories. Do not drop missing values,
change denominators, merge categories for visual convenience, or relabel the
reference as a census. Category ordering comes from `category_order`.

`VALID-05` — Link charts to the exact persona sample used for the displayed
study: sample ID/run name, seed where available, number of draws, reference
respondent count, and age reference year. Validation charts describe the persona
sample, not the changing model output. Changing a results date must not pretend
that a fixed persona sample's distribution changed.

`VALID-06` — Show total variation and maximum absolute percentage-point gap as
small supporting annotations or accessible tabular values, using saved summary
metrics. Do not invent a representativeness pass/fail threshold. The caption
must identify “sampled persona draws” and “weighted state CES reference.”

## 12. Discussion, costs, and footer

### 12.1 Discussion

**Owner layout override:** Use approximately 1,500 words of temporary Latin in
Discussion, preserving its navigation anchor. The owner will write
this section; the guidance below must not be auto-populated into the page.

`DISC-01` — Explain the difference between synthetic responses, actual polling,
winning odds, and model-implied seat allocations. Address persona composition,
small state reference pools, repeated draws, omitted/failed responses, model
differences, temporal context, and the limitations of grouped Third party outputs.

`DISC-02` — The point cloud illustrates differences among sampled personas. Model
disagreement is another diagnostic, not a calibrated confidence interval. Do not
claim forecast accuracy without a specified out-of-sample evaluation.

`DISC-03` — Keep newspaper-style prose columns and, optionally, the approved
pull-quote treatment. Do not add fake citations or describe proposed polling,
news, market, or daily automation integrations as already operating.

### 12.2 Costs

`COST-01` — Show all queried study models in a lean table. DEFAULT columns:
model, initial unique requests, validation retry requests, latest recorded cost,
and cumulative recorded cost. Clearly state the date window and currency.

`COST-02` — Count actual attempts from request logs/provider usage, not expanded
persona rows. A respondent drawn four times creates one initial logical request,
not four charges. Include retries, including unsuccessful responses if the
provider reports their charge. Preserve attempt history for this calculation.

`COST-03` — Missing cost is unknown, not zero. If some attempts lack charges,
label totals as known/reported costs and show how many charges are missing. Do
not invent a price from memory or infer that a provider's free model name proves
every recorded charge is exactly zero. Currency defaults to provider-reported USD.

`COST-04` — DEFAULT dollar display is two decimals; positive costs below $0.01
may display as “<$0.01.” Keep unrounded values in stored data. If later reporting
CAD, require an explicit exchange-rate source/date rather than silently converting.

### 12.3 Footer

`FOOT-01` — Provide project title, Methods anchor, and source-repository link when
its public destination is confirmed. Include concise data/source attribution.
Do not publish a guessed repository URL or an unverified author/affiliation.

## 13. Data meaning, normalization, and contracts

### 13.1 Existing repository inputs

Paths below are repository-relative. These are existing inputs, not permission
to overwrite analysis results during website rendering.

| Input | Purpose |
| --- | --- |
| `src/create_personas.py` | State set and weighted-with-replacement sampling. |
| `src/query_llms.py` | Request construction, parsing, result expansion, summaries. |
| `src/helper_query_validation.py` | Finite/bounded/sum validation and persisted retry budget. |
| `src/persona_text.py` | List/sentence descriptions and missing-field handling. |
| `config/query_config.yaml` | Model definitions, options, prompt levels/styles. |
| `config/persona_validation.yaml` | Default feature list, age bins/year, missing groups. |
| `config/ces_codes/ces25_value_labels.yaml` | CES field/category labels. |
| `data/personas/sample_100/*.parquet` | Current 100-draw state samples. |
| `data/personas/sample_100/persona_config.yaml` | Sampling seed and tracking metadata. |
| `data/llm_responses/<run>/results.parquet` | One expanded result per sampled row/configuration. |
| `data/llm_responses/<run>/summary.parquet` | State/configuration means and quality fields when available. |
| `data/llm_responses/<run>/responses.jsonl` | Raw attempt history; not necessarily present in a fresh clone. |
| `data/llm_responses/<run>/run_metadata.json` | Invocation arguments/times and newer validation counts. |
| `data/persona_validation/<sample>/` | Distribution tables, summary metrics, metadata, reference plots. |

`DATA-01` — Existing folders include `mercury-100`, `probe`, and `probe2` as of
this specification. Their existence is not proof of comparable full-state
coverage, current schemas, or multiple days of history. Inspect their actual
metadata and dimensions. Older probe outputs must not be silently promoted to a
complete second-model production snapshot.

`DATA-02` — Normalize analysis outputs into website data during a preparation
step. Keep the original files authoritative. The public website should read
small static JSON or equivalent browser-readable data, not execute the query
pipeline to render a page or attempt to load arbitrary local Parquet paths.

### 13.2 Configuration contract

`DATA-03` — Maintain one docs/study configuration defining the following
concepts. File naming is a DEFAULT; a proposed location is `docs/site-config.yml`.
Actual model lists and experimental settings remain OPEN, not sample-filled.

| Configuration concept | Required meaning |
| --- | --- |
| `query_models` | Explicit models to query each day; no accidental provider default of all available model definitions. |
| `headline_models` | Owner-approved ordered subset shown in the headline. |
| `timeseries_models` | All study models offered in the detailed chart checkboxes; readers select the visible subset. Do not limit this to the headline models. |
| `timeseries_default_models` | Initial selected subset; a subset of available time-series models. |
| Overview model list | All configured study models, in explicit order; not derived from current checkbox selection. |
| Experimental settings | Persona level, format, prompt style, context condition, and exact source sample. |
| Model display definitions | Model key, readable label, pinned provider ID, stable shape/line-style identity. |
| Time settings | Canonical daily reporting timezone, display timezone, collection schedule. |
| Baseline location | Verified seat-baseline input and its version/as-of information. |
| Source definitions | Polling/market adapters and source-specific mappings; unset sources remain unset. |

Validate that lists are consistent before rendering. A headline model must belong
to the study model universe. Do not mix settings within a line or silently switch
to a different prompt configuration to obtain a newer result.

### 13.3 Snapshot manifest

`DATA-04` — Store an explicit manifest for each archived snapshot. Minimum fields:

| Field | Meaning |
| --- | --- |
| `snapshot_id` | Stable unique ID for this dated collection; reruns resume this ID rather than overwrite another date. |
| `reporting_date` | Canonical calendar date for historical filtering. |
| `collected_at_utc` | Actual collection timestamp; display may convert to the configured local zone. |
| `model_key`, `model_id`, `model_snapshot` | Requested model and returned provider version where available. |
| `configuration_id` | Unambiguous persona/prompt/context condition. |
| `persona_sample_id` | Stable link to the sampled rows and validation outputs. |
| `context_id` | Dated context artifact identity, or explicit no-context condition. |
| `expected_states`, `expected_draws_per_state` | Expected coverage, normally 35 and 100. |
| Quality/coverage | State counts, valid/invalid counts, completion status, unresolved failures. |
| Data paths | Portable paths to state summaries and persona probabilities. |
| Publication status | Eligible, partial, failed, or pending, with the reason where relevant. |

Do not derive historical observation dates solely from file modification times.
Do not overwrite an old manifest to make a run look current. API request content
and archived source inputs support reproducibility; this specification does not
reintroduce Git revision lookups or a duplicate full-config block into query run
metadata, which the owner explicitly requested removing.

### 13.4 Persona probabilities and state summaries

`DATA-05` — Browser-facing persona rows need snapshot/configuration/model, state,
sample-row identity, stable site-local respondent identity, validity/status, and
the four probability values. Preserve the 100 draw positions for complete runs.
Data may be compressed into arrays, but the meaning must remain equivalent.

`DATA-06` — State summaries need the same identity fields, four means, expected
draws, valid draws, excluded draws, unique respondents, completion/quality, and
actual source timestamp. Reuse compatible saved summaries or independently
verify an adapter's recomputation against them.

`DATA-07` — Four canonical columns and display order:

| Column | Display | Role |
| --- | --- | --- |
| `p_democrat` | Democrat | Probability, mean, and eligible winner category. |
| `p_republican` | Republican | Probability, mean, and eligible winner category. |
| `p_third_party` | Third party / independent | Probability, mean, and grey winner category. |
| `p_would_not_vote` | Would not vote | Probability/mean only; never a winning Senate-seat category. |

`DATA-08` — Store probabilities as fractions. Multiply by 100 only for display.
Check finite numeric values, inclusive [0,1] bounds, and absolute sum error at
most `1e-6`. Use the existing helper's validation logic where practical. Do not
silently normalize invalid outputs. Use full precision for means and winners;
round only text labels. DEFAULT share display precision is one decimal place.

`DATA-09` — All four category means use the same valid-row mask. Exclusions are
counted by draws as well as unique respondents. A refusal is missing response
information, not a Would not vote response. No valid rows means null averages,
not a zero-filled vector.

### 13.5 External observations and baseline data

`DATA-10` — External observations carry source, metric type, state/race,
candidate/party mapping, value, observation time, retrieval time, and original
link/identifier. Poll observations additionally retain population and fieldwork
metadata. Market observations retain contract/outcome IDs and settlement meaning.

`DATA-11` — Metric type is mandatory: for example `vote_intention_share` versus
`market_win_probability`. Never join these as interchangeable `probability`
columns. Enforce `POLL-05` and `ODDS-01`–`10` at the adapter/render boundary.

`DATA-12` — Baseline seat data contains unique seat ID, state/class, fixed versus
contested classification, party/independent display category, source, and as-of
date. Assert 65 fixed and 35 contested in the configured election. Party totals
are data-derived, not repeated literals in chart JavaScript.

## 14. Interaction ownership and section independence

| Interaction | Changes | Must not change |
| --- | --- | --- |
| Navigation link | Scroll position/URL anchor. | Any selected model/date or data values. |
| Time-series state dropdown | Four response panels, their polling data, and the compact Polymarket odds chart. | Headline, state grid, persona-match state. |
| Time-series model checkboxes | Model traces/clouds in those four panels. | Headline model list, any overview model rows, source-data archive. |
| State-grid date dropdown | All 35 panels for Latest or the selected date. | Headline freshness or detailed time-series domain. |
| Persona-match state dropdown | All validation feature plots. | Any model result or results date. |
| Hover/focus | Explanatory tooltip only. | Selection state, axis range, underlying numbers, API calls. |

`INTERACT-01` — There are no other MVP data-selection controls. Do not add a
global store that unintentionally binds these separate state/date choices.

`INTERACT-02` — Defaults should be deterministic. Model order and identity do
not depend on network response order. A selection update redraws the relevant
charts without scrolling the page to the top or rebuilding the entire document.

## 15. Freshness, history, and publication behaviour

`HIST-01` — Collection is DAILY, not every two days. Keep the exact same approved
persona sample across days for comparable time series unless the study owner
explicitly changes the sampling design. A sample change creates a new series
identity; do not connect it invisibly to the old sample's line.

`HIST-02` — Record actual timestamps. DEFAULT storage is UTC and display timezone
is `America/Toronto`, with ET/UTC clearly labelled. Canonical reporting-day choice
remains `OPEN-08` and must be consistent between manifests and the date selector.

`HIST-03` — “Latest” selects by actual eligible snapshot metadata, never directory
name sort alone. Daily runs can finish at different times. Preserve per-model
as-of information rather than representing yesterday's result as today's.

`HIST-04` — Publish real single-day data as a single observed point. Do not fill
the chart with mock history to make it look like the design image. A missing day
is missing; show no observation for it and explain a visible gap where useful.

`HIST-05` — Do not create a shared mean across incompatible prompt styles,
formats, levels, model versions, or news conditions. A material condition/version
change must be recorded and indicated by a new series or explicit discontinuity.

`HIST-06` — Polling freshness follows source observation dates, not the LLM
schedule. Current polling source and refresh frequency are open. A source failure
must not erase good archived data or replace an unavailable value with zero.

## 16. GitHub Actions and Quarto architecture

**Hosting clarification (26 October 2026):** Render locally from `docs/` into
the repository-root `docs/` folder and commit the rendered bundle. GitHub Pages
uses Deploy from a branch with `/docs`. Do not add a custom publishing workflow.
Daily data collection Actions remain future work, separate from static hosting.

**Status:** Required architecture direction; schedules, sources, credentials,
budgets, and deployment destination require the open settings above.

`BUILD-01` — Render static Quarto HTML with client-side interactive charts. The
published site must work on GitHub Pages without a Python server, Shiny server,
database service, or browser-held API credential. Static data-file fetches from
the published site are permitted.

`BUILD-02` — Separate acquisition from rendering. A normal content/style commit
must be able to rebuild the site from saved data without querying models. Quarto
rendering, local preview, browser reloads, and selector changes must never call
LLMs or create paid external requests.

`AUTO-01` — A daily acquisition workflow should: check snapshot identity; obtain
approved external inputs/context if configured; query the explicit model list;
run existing validation/retries; archive attempts/results/metadata; prepare website
data; check coverage; and invoke the publishing stage if eligible.

`AUTO-02` — Reuse the current validation workflow: finite inclusive [0,1] values,
sum tolerance `1e-6`, at most three additional validation attempts, persisted retry
counts, whole-vector exclusions, and per-state metadata. Existing transport
retries are separate. Do not implement a second conflicting validity definition
inside the website or CI scripts.

`AUTO-03` — Give each reporting-date/configuration collection a distinct run ID.
Retrying that same daily run resumes it. Do not reuse one undated run name forever,
because valid cached responses would then prevent fresh daily model queries.

`AUTO-04` — Prevent overlapping acquisition for the same snapshot. Verify
idempotency before calls so a scheduled run and manual retry cannot double-charge
the same completed work. Persist the archive before deploying; Actions runner
disk and disposable caches are not the authoritative historical store.

`AUTO-05` — Keep credentials in repository/environment secrets. Do not put .env,
authorization headers, or API keys in source, rendered HTML, client JavaScript,
public manifests, or logs. Only publish the data needed for the research display;
raw prompts/attempt archives need an explicit storage/publication decision.

`AUTO-06` — Provide a manual workflow trigger for recovery. Schedule at a defined
time after resolving `OPEN-08`; do not promise exact real-time execution from
GitHub's scheduled runner. A failed collection preserves the last good published
site and its truthful timestamp rather than replacing it with empty charts.

`AUTO-07` — Rendering/publishing reads an explicit selected archive/manifest. Do
not let a data-preparation script accidentally render stale frozen outputs after
new data arrives. Verify rendered values and as-of labels against the selected
manifest. Review Quarto caching/freeze settings for the chosen architecture.

## 17. Failure states and reader-facing messages

| Condition | Required behaviour |
| --- | --- |
| No eligible result for a configured headline model | Keep its row and show unavailable; no replacement model or fabricated count. |
| Missing state/model on a selected historical date | Retain the state/model row with unavailable text; no silent borrowing from another date. |
| One genuine historical snapshot | Show one point; no invented trend. |
| No selected time-series models | Explain that a model must be selected; other sections remain unchanged. |
| Partial valid persona coverage | Draw valid values only; expose expected/valid/excluded counts. Apply the agreed publication policy to headline allocation. |
| Entirely invalid state/model | Null/no numeric mean, no zero line, no inferred winner. |
| Polling source unset/unavailable | Model charts still work; concise availability note without an empty extra benchmarks section. |
| Non-vote polling not supplied | No polling trace in that panel; do not use undecided share as a substitute. |
| Polymarket market/outcome/history unavailable | Keep the compact odds chart's availability message; do not place market odds on response-share axes or substitute another race. |
| Baseline not verified | Do not publish production seat totals as fact; retain an explicit baseline-pending state. |
| Model request fails after retries | Preserve attempt history and exclusion counts; no infinite re-prompt loop. |
| Provider cost missing | Unknown/partial cost label, not $0.00. |
| New daily workflow fails | Preserve previous published snapshot and its actual date. |
| Fixture data used for design review | Persistent, unmistakable “Illustrative data” label; never mix with real data unnoticed. |

## 18. Accessibility and usable chart behaviour

`ACCESS-01` — Target WCAG 2.2 AA. At minimum, meet applicable text contrast,
keyboard operation, focus visibility, label, reflow, and non-colour-identification
requirements. Test chart/control accessibility rather than assuming the charting
library supplies it automatically.

`ACCESS-02` — Use semantic headings in logical order. Every selector has a
visible label and keyboard focus. Navigation and controls work without a mouse.
Do not rely on a tiny coloured swatch as the only label for a model or category.

`ACCESS-03` — Supply accessible equivalents for chart means, dates, category
shares, seat counts, and exclusion counts. Informational hover details should
also be reachable on focus or through accompanying accessible text/table data.
This must not require adding an unapproved data-selection control.

`ACCESS-04` — Respect reduced-motion settings. DEFAULT updates use no decorative
animation; any brief transition must not distort comparisons. Do not auto-scroll,
autoplay dates, or animate through models.

## 19. Performance and data loading

`PERF-01` — Load compact summaries for headline and the overview. Load detailed
persona data for the selected state lazily where appropriate. Do not initially
render every persona point for all 35 states and every date in hidden charts.

`PERF-02` — Performance improvements may compress data, reuse arrays between the
four categories, cache static files, or use a suitable canvas/WebGL renderer.
They may not silently reduce the required 100-row clouds to unique respondents
or a random subset, remove required models/features, or replace means with medians.

`PERF-03` — DEFAULT acceptance fixture: 35 states, 4 models, 30 reporting dates,
100 sampled rows per complete state/model/day. With data loaded, state/model/date
selection should update within roughly 500ms on a normal desktop. Treat this as
a target to measure, not a claim already established.

`PERF-04` — Reserve chart heights so late data loading does not substantially
shift the article. Share one copy of the charting library; avoid large framework
dependencies solely to support two selectors and a date dropdown.

## 20. Suggested file/component boundaries for different agents

The following structure is a DEFAULT implementation plan, not files created by
this specification. Adapt names only if the interfaces and ownership stay clear.

```text
docs/
  _quarto.yml                    # static project/render settings
  index.qmd                      # approved section order and narrative content
  site-config.yml                # explicit model lists, conditions, display settings
  styles.scss                    # all shared visual tokens and responsive layout
  assets/js/
    headline.js                  # render precomputed seat totals
    timeseries.js                # local state/model selectors; four panels + state-linked odds chart
    state-grid.js                # local Latest/historical date selector; all models
    persona-validation.js        # local state selector; every validated feature
  data/                          # generated public data, not hand-edited analysis
  design/
    approved-mockup.png           # handoff visual reference; not the page background
  DESIGN_REQUIREMENTS.md          # this specification; exclude from public render
scripts/
  prepare_website_data.py         # normalize and check saved inputs without API calls
.github/workflows/
  collect-daily.yml               # acquisition; explicit configuration/credentials
docs/                            # rendered static bundle committed for branch Pages
```

| Work area | Responsibilities | Required handoff evidence |
| --- | --- | --- |
| Data preparation | Manifest/schema, means, winners, baseline, model universe, snapshot/date filtering, cost reconciliation. | Small known-answer fixtures; source-to-output reconciliation; missing-data behaviour. |
| Quarto/layout | Masthead, section order, CSS tokens, responsive rules, narrative placeholders, anchors. | Screenshots at desktop/tablet/phone widths; no default-theme duplication. |
| Interactive charts | Selection ownership, 100-row model-shaped clouds, means, polling overlays, overview/all-model rows, full validation features. | Interaction checks proving one section does not mutate another; accessible values. |
| Automation | Daily acquisition, bounded resumable calls, durable archives, no paid calls during rendering, deployment. | Mocked workflow tests and an offline rendering path; secret handling and retry/idempotency evidence. |
| Review/QA | Numerical accuracy, visual fidelity, accessibility, date/model isolation, unresolved choices. | Acceptance matrix results referencing IDs below and any deviations. |

Agents should agree on the normalized schema before implementing separate chart
components. Changes to shared tokens, model identity, category names, or snapshot
meaning require coordinated updates rather than local workarounds. Do not create
multiple independent copies of the same computation in Python and JavaScript.

## 21. Test fixtures and mathematical examples

Use isolated synthetic fixtures for development, clearly separate from real
results. Never modify source persona files to exercise a chart edge case.

### 21.1 Multiplicity example

Respondent A appears three times with D probability 0.20; respondent B appears
once with D probability 0.80. The displayed mean is:

```text
(3 * 0.20 + 1 * 0.80) / 4 = 0.35
```

The cloud contains four sampled-row markers, with three sharing A's y value.
The mean is not `(0.20 + 0.80) / 2 = 0.50`.

### 21.2 Exclusion example

Six expected draws include four valid and two invalid rows. All four category
means use the same four valid rows. Report 2 excluded draws and 33.33% excluded.
If those two invalid rows repeat the same respondent, report one excluded unique
respondent. Do not show six valid points or include one present component from
an otherwise incomplete vector.

### 21.3 Winner examples

| D | R | Third party | Non-vote | Allocation |
| --- | --- | --- | --- | --- |
| 0.44 | 0.42 | 0.04 | 0.10 | Democrat; no >50% requirement. |
| 0.30 | 0.25 | 0.35 | 0.10 | Grey Independent/other. |
| 0.20 | 0.25 | 0.05 | 0.50 | Republican; Non-vote cannot win a seat. |
| 0.40 | 0.40 | 0.05 | 0.15 | Unallocated tie under the default tie rule. |
| null | null | null | null | Unavailable, not independent or a 0% result. |

### 21.4 Required visual/interaction edge cases

Include two versus four models, long model labels, all model checkboxes cleared,
one historical day, missing intermediate days, incomplete persona coverage,
missing historical model/date, absent polling, all-zero Third party share in a
valid vector, nonzero independent seats, long validation category names, unknown
validation codes, and a model not included in the headline but present in every
state panel.

## 22. Acceptance and review checklist

These are observable checks for the completed website. A screenshot alone is
insufficient for data and control requirements.

| Test ID | Requirements | Acceptance check |
| --- | --- | --- |
| `QA-01` | `CORE-01`, `BUILD-01` | Quarto renders an HTML site that works as static GitHub Pages content, including repository-subpath asset URLs. |
| `QA-02` | `PAGE-01`–`04`, `INTRO-03` | Introduction precedes headline; synthetic label is visible; all sections/anchors are in the specified order; no external benchmarks block. |
| `QA-03` | `STYLE-*`, `LAYOUT-01` | At 1440 × 900, the compact introduction and initial two-model hero are above the fold; visual hierarchy matches the reference. |
| `QA-04` | `LAYOUT-02`–`04` | Check 360px, 768px, 1024px, and 1440px widths for reflow, readable labels, no page overflow, and no missing panels. |
| `QA-05` | `HEAD-02`–`04` | Headline uses only owner-configured models and freshest eligible results, with truthful timestamps; other selectors cannot mutate it. |
| `QA-06` | `HEAD-05`–`12` | Baseline totals 65; contested plus unallocated totals 35; total is 100 for every model; grey independent and unallocated encodings differ. |
| `QA-07` | `HEAD-07`–`08` | All winner fixtures in section 21.3 pass, using means before rounding and excluding Non-vote. |
| `QA-08` | `TIME-01`–`04` | Only state/model selection controls exist in time series; zoom/pan/legend selection are absent; hover/focus remains informative. |
| `QA-09` | `TIME-07`–`11` | A complete 100-draw model/state/day produces 100 markers per panel; repeated rows remain; model shapes stay stable after toggling. |
| `QA-10` | `TIME-12`, `DATA-08`–`09` | Multiplicity and exclusion fixtures produce 0.35 and the correct shared-valid-row averages; no extra commonweight is applied. |
| `QA-11` | `POLL-01`–`05` | Compatible polls overlay the response plots with distinct styling and source dates; missing series stay missing; no market odds on response-share axes. |
| `QA-12` | `GRID-01`–`07` | Exactly 35 state panels in the specified order; every study model appears; date is the only grid selection control. |
| `QA-13` | `GRID-03`, `INTERACT-*` | Historical selection changes only the grid; missing model/date remains unavailable; time-series model deselection does not remove overview rows. |
| `QA-14` | `VALID-01`–`06` | Every saved validation feature/category is present, currently all five fields, with source shares/order/denominators preserved. |
| `QA-15` | `COST-01`–`04` | Costs reconcile to actual attempts, including retries, without charging expanded repeated draws; missing charges remain unknown. |
| `QA-16` | `HIST-01`–`06` | Real snapshot dates/version/sample identities drive history; no mock history, silent sample change, or fabricated daily polling. |
| `QA-17` | `AUTO-01`–`07` | Mocked daily workflow archives outputs and resumes bounded requests; normal Quarto render/preview/browser use makes zero LLM calls. |
| `QA-18` | `ACCESS-*` | Keyboard selectors, visible focus, meaningful chart values, consistent model shapes, contrast, and responsive accessible reading order verified. |
| `QA-19` | `PERF-*` | The 4-model/30-day fixture loads selected-state detail without rendering all 35 states' persona histories; interaction timing measured. |
| `QA-20` | Section 17 | Unavailable, all-invalid, partially valid, polling-missing, baseline-pending, and failed-update states remain truthful and readable. |
| `QA-21` | `ODDS-01`–`04` | One compact odds chart follows the four response panels, shares their state/date window, has a separate labelled 0–100% winning-odds axis, and adds no controls. |
| `QA-22` | `ODDS-02`, `INTERACT-02` | Changing the state updates odds; toggling model checkboxes leaves market values and visibility unchanged; headline and grid remain unchanged. |
| `QA-23` | `ODDS-05`–`10` | Verify general-election outcome mapping, prior-to-cutoff timestamp matching, stale/missing coverage behaviour, raw quote provenance, and no fabricated complementary outcomes or normalization. |

Final handoff should include changed files, instructions to render locally,
screenshots of representative widths, acceptance results, known missing data,
remaining OPEN items, and confirmation of whether any live requests/deployment
occurred. Do not describe a fixture-based preview as a live election tracker.

## 23. Decision history and superseded mockup details

| Decision | Current requirement |
| --- | --- |
| Approved original newspaper layout | Retain editorial appearance and single-page research narrative. |
| Introduction moved above headline | Required, while keeping headline results prominent. |
| Polling added directly over time-series plots | Required for compatible vote-intention data. |
| External benchmarks section removed | Must stay removed. |
| Time-series controls narrowed | Only state and model subset selection; mockup's extra toggles are superseded. |
| Fixed Senate seats identified | Precompute 65-seat baseline, then add 35 contested outcomes. |
| Owner clarified winner rule | Largest averaged D/R/Third probability, even below 50%; exclude Non-vote. |
| Independent outcome clarified | Grey independent/non-major-party seat category. |
| Cadence revised | DAILY model collection replaces every-two-days discussion/text. |
| Persona cloud clarified | All 100 sampled response rows; different light shapes distinguish models. |
| Model visibility clarified | Headline list owner-defined; time-series subset selectable; overview shows all study models. |
| Initial Polymarket deferral | Superseded by the subsequent compact-odds-chart approval. |
| Compact Polymarket chart approved | Add one state-linked winning-odds chart under the four response panels; no new controls, response-share overlay, headline market row, or external benchmarks section. Contract mapping and data quality settings remain open. |

When the owner resolves an open item, update its status and this history. If a
change alters model interpretation, denominators, seat allocation, control scope,
or data freshness, update the corresponding acceptance check at the same time.

## 24. References for implementing agents

* [Approved design image](design/approved-mockup.png): layout reference, not data.
* [Quarto GitHub Pages publishing](https://quarto.org/docs/publishing/github-pages.html): official publishing guidance. Acquisition/render separation is an additional requirement of this project.
* [GitHub scheduled workflow documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): verify schedule behaviour when implementing CI.
* [WCAG 2.2](https://www.w3.org/TR/WCAG22/): accessibility target and criteria.
* [Official Senate roster](https://www.senate.gov/senators/): starting point for verifying the fixed-seat baseline; also verify the configured election's contested/special-election set.
* [Polymarket pricing and historical-data documentation](https://docs.polymarket.com/market-data/prices-order-books#price-history): outcome history and observation-time semantics; verify current API details during implementation.
* [Polymarket market discovery](https://docs.polymarket.com/market-data/discover-markets): contract/outcome discovery; review actual race and resolution rules before persisting the mapping.
* Repository source/configuration paths in section 13.1: inspect current files before implementing because schemas and study settings may evolve.

The original reference image was copied unchanged from the final approved
generated mockup, `exec-0154953c-7273-46cd-a707-ffcb9ac022e1.png`. The repository
copy makes this handoff portable; no agent needs the author's local generated-
image directory to understand the intended layout.
