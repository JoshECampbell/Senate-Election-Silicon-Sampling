"""Build the static website from dated saved runs; no network or model requests.

Workflow: discover -> validate each model/day -> retain eligible 100-draw states
-> generate dated figures/data -> assemble latest page components. Quarto then
renders index.qmd, which only includes the prepared components. See docs/README.md.
Usage (repository root): uv run python src/prepare_website.py
"""

from argparse import ArgumentParser
from html import escape
import json
import hashlib
from pathlib import Path
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from site_data import CATEGORIES, SEAT_CATEGORIES, load_history, headline_outcome, cumulative_usage
from site_figures import senate_figure, response_figure, state_figure, validation_figure, seat_distribution_figure
from polling_forecast import add_forecasts
from forecast import add_corrected_forecasts


def percent(value, digits=0):
    return f'{100*value:.{digits}f}%'


def chance(value):
    """A simulation share; never round a rare outcome down to 0% or up to 100%."""
    if 0 < value < 0.01:
        return '&lt;1%'
    if 0.99 < value < 1:
        return '&gt;99%'
    return percent(value)


def corrected_headline(key, model, day, forecast):
    """Corrected forecast block for one model's headline card."""
    seats = forecast['seats']
    rep, dem = seats['republican_majority'], seats['democratic_majority']
    if rep >= dem:
        outcome, colour = f'Republican majority in {chance(rep)} of simulations', '#BD4942'
    else:
        outcome, colour = f'Democratic majority in {chance(dem)} of simulations', '#326A9D'
    return (f'<div class="corrected-forecast"><p class="eyebrow">Corrected forecast</p>'
            f'<p class="projection-outcome" style="color:{colour}">{outcome}</p>'
            f'<p class="corrected-seats">Democrats: median <b>{seats["median"]}</b> seats '
            f'(90% range {seats["low"]}–{seats["high"]}) &middot; Democratic majority in {chance(dem)} '
            f'&middot; no outright majority in {chance(seats["no_majority"])}</p>'
            f'<img class="wide-figure" src="figures/{day}/forecast/{key}.svg" alt="{escape(model["label"])}: '
            f'Democratic seats across {seats["draws"]:,} simulated elections, median {seats["median"]}, '
            f'90% range {seats["low"]} to {seats["high"]}"></div>')


def forecast_table(history):
    """Latest corrected state forecasts per model, beside the polling benchmark."""
    synthetic = [(k, m) for k, m in history['models'].items() if m.get('kind') != 'external_forecast']
    latest = {k: history['latest'][k] for k, _ in synthetic}
    forecasts = {k: history['snapshots'][d]['models'][k]['forecast'] for k, d in latest.items()
                 if d and history['snapshots'][d]['models'][k].get('forecast')}
    polls_day = history['latest'].get('polling_forecast')
    polls = history['snapshots'][polls_day]['models']['polling_forecast']['states'] if polls_day else {}
    if not forecasts:
        return '<p class="empty-state">No corrected forecast is available.</p>'
    order = sorted(history['states'], key=lambda s: sum(f['states'][s]['corrected_share'] for f in forecasts.values()))
    head = ''.join(f'<th scope="col">{escape(m["label"])}<span>{latest[k]}</span></th>' for k, m in synthetic if k in forecasts)
    rows = []
    for state in order:
        cells = []
        for key, _ in synthetic:
            if key not in forecasts:
                continue
            row = forecasts[key]['states'][state]
            colour = '#326A9D' if row['dem_win_chance'] >= 0.5 else '#BD4942'
            cells.append(f'<td><b style="color:{colour}">{percent(row["corrected_share"], 1)}</b>'
                         f'<span>{percent(row["low"])}–{percent(row["high"])}</span>'
                         f'<span>D wins {chance(row["dem_win_chance"])}</span></td>')
        poll = polls.get(state)
        if poll:
            column = 'p_third_party' if poll.get('left_party') == 'I' else 'p_democrat'
            label = ' (I)' if poll.get('left_party') == 'I' else ''
            cells.append(f'<td>{percent(poll["means"][column], 1)}{label}</td>')
        else:
            cells.append('<td>Unavailable</td>')
        rows.append(f'<tr><th scope="row">{escape(history["states"][state]["name"])}</th>{"".join(cells)}</tr>')
    settings = history['forecast_settings']
    return (f'<table class="cost-table forecast-table"><caption>Corrected Democratic share of the two-party vote, '
            f'by state and model</caption><thead><tr><th scope="col">State</th>{head}'
            f'<th scope="col">Polling Forecast<span>{polls_day or "Unavailable"}</span></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            f'<p class="figure-caption">Each model cell shows the corrected share, its 90% range and the share of '
            f'{settings["draws"]:,} simulated elections that Democrats win. States run from the most Republican to the '
            f'most Democratic average corrected share. Corrections map each model\'s share through the intercept and '
            f'slope fitted on its 2024 presidential back-cast; simulations add persona resampling, a state error equal to '
            f'the back-cast residual and an assumed national error (SD {settings["national_sd"]:.2f} on the logit scale). '
            f'Polling Forecast shows its implied two-candidate share for the leading non-Republican candidate; '
            f'(I) marks an independent. Synthetic results, not measured voter intentions.</p>')


def write(path, content):
    # Preserve mtimes and avoid Git churn when data/components are unchanged.
    if path.is_file() and path.read_text(encoding='utf-8') == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path, value):
    write(path, json.dumps(value, indent=2, allow_nan=False))


def options(states, selected):
    return "".join(f'<option value="{key}"{" selected" if key==selected else ""}>{escape(v["name"])}</option>' for key,v in states.items())


def legend(validation=False):
    entries = [("Persona draws", "#326A9D"), ("Weighted CES reference", "#343434")] if validation else [(label,colour) for _,label,colour in CATEGORIES]
    return '<div class="legend">'+"".join(f'<span><i style="background:{colour}"></i>{escape(label)}</span>' for label,colour in entries)+'</div>'


def validation_comparison_table(state, features):
    """Show all cohort distances on the 0-1 scale, in the plot's feature order."""
    rows = []
    for feature in features:
        cells = ''.join(f'<td>{state["validation_cohorts"][str(size)][feature["key"]]:.3f}</td>'
                        for size in (25, 50, 100))
        rows.append(f'<tr><th scope="row">{escape(feature["name"])}</th>{cells}</tr>')
    return ('<table class="cost-table validation-comparison">'
            f'<caption id="validation-comparison-caption">{escape(state["name"])}: TVD by cohort size</caption>'
            '<thead><tr><th scope="col">Persona characteristic</th>'
            '<th scope="col">25 Cohort</th><th scope="col">50 Cohort</th>'
            '<th scope="col">100 Cohort</th></tr></thead>'
            f'<tbody id="validation-comparison-body">{"".join(rows)}</tbody></table>'
            '<p class="figure-caption">TVD (total variation distance) ranges from 0 to 1; '
            'lower values indicate closer agreement with the weighted state CES reference. '
            'Each cohort contains the stated number of draws per state, with replacement. '
            'These comparisons describe one saved cohort at each size, not repeated sampling experiments.</p>')


def overview_records(history, state, selection):
    """Historical means exactly that day. Latest uses each complete model's day."""
    values = {}
    for key in history['models']:
        day = history['latest'][key] if selection=='latest' else selection
        entry = history['snapshots'].get(day,{}).get('models',{}).get(key)
        if entry:
            values[key] = {**entry['states'][state], 'date':day}
    return values


def latest_overview_prefix(history):
    """Reuse the dated grid unless Latest actually needs to mix model dates."""
    latest=history['date']
    same=all(overview_records(history,state,'latest')==overview_records(history,state,latest)
             for state in history['states'])
    return f'figures/{latest}/'+('states' if same else 'states-latest')


def prune_superseded_figures(site, history):
    """Apply the approved retention policy to known generated SVGs only.

    Daily state/headline figures and all data exports are archives. Cumulative
    responses and a mixed-date Latest grid are current views, not daily archives.
    Leave unrecognized filenames, directories and all source data untouched.
    """
    figures=(site/'figures').resolve()
    if not figures.is_relative_to(site.resolve()):
        raise ValueError('Figure directory must remain inside the website.')
    latest=history['date']
    current_grid=latest_overview_prefix(history)
    for folder in figures.iterdir():
        try:
            day=date.fromisoformat(folder.name).isoformat()
        except ValueError:
            continue
        if day>latest:
            continue
        for kind in ('responses','states-latest'):
            if (kind=='responses' and day>=latest) or f'figures/{day}/{kind}'==current_grid:
                continue
            target=(folder/kind).resolve()
            if not target.is_relative_to(figures):
                raise ValueError('Managed figure path escaped the figure directory.')
            for state in history['states']:
                names=[f'{state}-{column}.svg' for column,_,_ in CATEGORIES] if kind=='responses' else [f'{state}.svg']
                for name in names:
                    path=target/name
                    if path.is_file():
                        path.unlink()
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()


def public_history(history, points=False):
    """Exclude category tables and bulky persona points from the page manifest.

    Dated exports retain anonymous draw probabilities for reproducibility; the
    shared manifest keeps the state means, eligibility, provenance and paths.
    Raw CES IDs, prompts and provider error bodies never enter either export.
    """
    public = json.loads(json.dumps(history,allow_nan=False))
    for state in public['states'].values():
        for value in state['validation'].values():
            value.pop('categories',None)
    if not points:
        for snapshot in public['snapshots'].values():
            for entry in snapshot['models'].values():
                for state in entry['states'].values():
                    state.pop('points',None)
    return public


class FigureCache:
    """Skip rendering when figure inputs AND the saved SVG still match.

    Content hashes, not mtimes, detect changes. Missing/edited SVGs are repaired.
    The disposable cache lives under the ignored docs/.quarto/ directory.
    """
    def __init__(self, site):
        self.site = site.resolve()
        self.path = self.site/'.quarto/site-figures.json'
        try:
            self.entries = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.entries = {}
        if not isinstance(self.entries, dict):
            self.entries = {}
        self.code = hashlib.sha256(Path(__file__).with_name('site_figures.py').read_bytes()).hexdigest()
        self.built = self.reused = 0

    def render(self, path, renderer, *args):
        key = path.resolve().relative_to(self.site).as_posix()
        payload = [self.code, renderer.__name__, CATEGORIES, SEAT_CATEGORIES, args]
        # Model insertion order affects row placement and x offsets. Preserve it
        # in the signature so reordering configured models invalidates the SVG.
        signature = hashlib.sha256(json.dumps(payload,allow_nan=False).encode()).hexdigest()
        previous = self.entries.get(key, {})
        output_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if previous.get('input') == signature and output_hash == previous.get('output') and output_hash is not None:
            self.reused += 1
            return
        write(path, renderer(*args))
        self.entries[key] = {'input':signature,'output':hashlib.sha256(path.read_bytes()).hexdigest()}
        self.built += 1

    def save(self):
        self.entries={k:v for k,v in self.entries.items() if (self.site/k).is_file()}
        write_json(self.path, self.entries)


def response_inputs(history, state, day):
    """Only this state's history through the as-of date affects its response SVG.

    Tomorrow's data cannot invalidate yesterday's SVG. Corrections to yesterday
    do invalidate the affected later cumulative charts.
    """
    dates = [d for d in history['dates'] if d<=day]
    snapshots = {}
    for d in dates:
        models = {}
        for key,entry in history['snapshots'][d]['models'].items():
            models[key] = {k:entry[k] for k in ('model_id','model_snapshots','collected_at')}
            models[key]['states'] = {state:entry['states'][state]}
        snapshots[d] = {'models':models}
    return {'dates':dates,'models':history['models'],'states':{state:{'name':history['states'][state]['name']}},'snapshots':snapshots}


def prepare(root=ROOT, output=None):
    history = load_history(root)
    add_forecasts(history, root)
    add_corrected_forecasts(history, root)
    site = output or root/'docs'
    generated = site/'components/_generated'
    latest = history['date']
    models = history['models']
    history['validation_prefix']=f'figures/personas/{history["sample"]}'
    cache = FigureCache(site)
    # Recheck saved inputs each time, but render only changed/missing figures.
    for day in history['dates']:
        figures = site/'figures'/day
        for state,info in history['states'].items():
            if day==latest:
                inputs = response_inputs(history,state,day)
                for column,_,_ in CATEGORIES:
                    cache.render(figures/f'responses/{state}-{column}.svg',response_figure,state,inputs,column,day)
            records = overview_records(history,state,day)
            cache.render(figures/f'states/{state}.svg',state_figure,info['name'],records,models)
        for key,entry in history['snapshots'][day]['models'].items():
            if entry['senate']:
                cache.render(figures/f'senate/{key}.svg',senate_figure,entry['senate'])
            if entry.get('forecast'):
                cache.render(figures/f'forecast/{key}.svg',seat_distribution_figure,entry['forecast']['seats'],models[key]['label'])
        daily = public_history({**history,'date':day,'dates':[day],'snapshots':{day:history['snapshots'][day]}},points=True)
        daily['latest'] = {key: day if history['snapshots'][day]['models'].get(key,{}).get('complete') else None for key in models}
        write_json(site/'data'/day/'snapshot.json',daily)
    # Latest overview can mix actual dates when a model missed today's run.
    # Each row prints its own observed date; historical selections never backfill.
    latest_prefix=latest_overview_prefix(history)
    for state,info in history['states'].items():
        if latest_prefix.endswith('/states-latest'):
            cache.render(site/latest_prefix/f'{state}.svg',state_figure,info['name'],overview_records(history,state,'latest'),models)
        for feature in history['features']:
            cache.render(site/history['validation_prefix']/f'{state}-{feature["key"]}.svg',validation_figure,info['name'],feature['name'],info['validation'][feature['key']])
    history['overview'] = {day:{'prefix':f'figures/{day}/states','label':f'Selected snapshot: {day}. Polling Forecast shows implied two-candidate shares.'} for day in history['dates']}
    history['overview']['latest'] = {'prefix':latest_prefix,'label':'Latest result per model / benchmark; actual dates shown on every row. Polling Forecast bars are implied two-candidate shares.'}
    write_json(site/'data/history.json',public_history(history))
    labels = ', '.join(v['label'] for v in models.values())
    write(generated/'_snapshot.html',f'<p class="snapshot-line">FORECASTED RESULTS <span>{history["dates"][0]} to {latest} &middot; {escape(labels)} &middot; 100 draws per synthetic model/state/day; external benchmark uses implied shares &middot; {escape(history["timezone"])}</span></p>')
    headlines = []
    for key,model in models.items():
        full_name=model.get('full_name',model['label'])
        day = history['latest'][key]
        if not day:
            headlines.append(f'<article class="headline-result"><h3>{escape(full_name)}</h3><p class="source-note">No complete 35-state snapshot available.</p></article>')
            continue
        entry = history['snapshots'][day]['models'][key]
        model_details = ('<p class="headline-model-id"><a href="https://www.pollingforecast.com/us/data">Polling Forecast</a></p>'
                         if model.get('kind') == 'external_forecast' else '')
        totals = entry['senate']['totals']
        outcome, outcome_colour = headline_outcome(totals)
        categories={row[0]:row for row in SEAT_CATEGORIES}
        counts = ''.join(f'<span><b style="color:{categories[k][3]}">{totals[k]}</b>{escape(categories[k][1])}</span>' for k in ('democrat','independent','republican'))
        if totals['unallocated']:
            counts += f'<span><b>{totals["unallocated"]}</b>Unallocated seats</span>'
        raw_label = '' if model.get('kind') == 'external_forecast' else '<p class="eyebrow">Raw projection (uncorrected)</p>'
        corrected = corrected_headline(key, model, day, entry['forecast']) if entry.get('forecast') else ''
        headlines.append(f'<article class="headline-result"><h3>{escape(full_name)}</h3>{model_details}{raw_label}<p class="projection-outcome" style="color:{outcome_colour}">{escape(outcome)}</p><div class="seat-counts">{counts}</div><img class="wide-figure" src="figures/{day}/senate/{key}.svg" alt="{escape(model["label"])}: {totals["democrat"]} Democratic, {totals["republican"]} Republican, {totals["independent"]} independent/other seats">{corrected}</article>')
    fixed=history['baseline']['fixed_seats']
    baseline_note=f"{fixed['democrat']} Democratic, {fixed['republican']} Republican and {fixed['independent']} independent seats"
    write(generated/'_headline.html',''.join(headlines)+f'<p class="data-note">Each model is projected independently. An outright party majority requires 51 seats. Independent/other seats remain unassigned to either party. The fixed baseline is {baseline_note}. The raw projection allocates 35 contests using the largest average voting-category probability, excluding "Would Not Vote". The corrected forecast first maps each model\'s state shares through the correction fitted on its 2024 presidential back-cast, then simulates {history["forecast_settings"]["draws"]:,} elections; the chart shows how often each Democratic seat total occurs (blue: Democratic majority, red: Republican majority, grey: neither). Polling Forecast allocates each contest to its implied two-candidate leader. Synthetic results, not measured voter intentions.</p>')
    write(generated/'_forecast.html',forecast_table(history))
    symbols = {'circle':'&#9679;','triangle':'&#9650;','square':'&#9632;', 'diamond':'&#9670;'}
    toggles = ''.join(f'<label><input type="checkbox" data-model-toggle="{key}" checked><span aria-hidden="true">{symbols[model["shape"]]}</span>{escape(model["label"])}</label>' for key,model in models.items())
    panels = ''.join('<div class="response-panel">'+(site/'figures'/latest/f'responses/georgia-{column}.svg').read_text(encoding='utf-8')+'</div>' for column,_,_ in CATEGORIES)
    coverage = []
    for day,snapshot in sorted(history['snapshots'].items()):
        for key,model in models.items():
            entry = snapshot['models'].get(key)
            eligible = sum(v['eligible'] for v in entry['states'].values()) if entry else 0
            coverage.append(f'<tr><td>{day}</td><td>{escape(model["label"])}</td><td>{eligible}/35</td><td>{escape(entry["run"]) if entry else "Not collected"}</td></tr>')
    write(generated/'_responses.html',f'''
<div class="section-toolbar"><label for="response-state">State <select id="response-state">{options(history['states'],'georgia')}</select></label><fieldset><legend>Models / benchmark</legend>{toggles}</fieldset></div>
<div id="response-chart" class="response-chart">{panels}</div>
<p id="model-empty" class="empty-state" hidden>Select at least one model to view response probabilities.</p>
<p class="figure-caption">Dots show variation among sampled personas, not a confidence interval. Lines show average model responses across all 100 sampled draws, including repeated respondents. Shapes identify models; horizontal jitter exposes overlap and is not a collection time.</p>
<table class="accessible-summary"><caption>Selected state's synthetic means and implied forecast shares</caption><thead><tr><th>Date</th><th>Model</th><th scope="col" data-category="p_democrat">Democrat</th><th scope="col" data-category="p_republican">Republican</th><th scope="col" data-category="p_third_party">Third party</th><th scope="col" data-category="p_would_not_vote">Would not vote</th></tr></thead><tbody id="response-means"></tbody></table>
<details><summary>Daily coverage and source runs</summary><table class="cost-table"><thead><tr><th>Date</th><th>Model</th><th>Complete states</th><th>Source run</th></tr></thead><tbody>{''.join(coverage)}</tbody></table><p class="source-note">Incomplete state samples are unavailable. No older snapshot is substituted into a historical date. The headline and Latest overview may use older complete model results, labelled with their actual dates.</p></details>
<p id="chart-announcement" class="sr-only" aria-live="polite"></p>''')
    cards = ''.join(f'<article class="state-card"><h3>{escape(info["name"])}</h3><img data-state="{key}" src="{latest_prefix}/{key}.svg" alt="{escape(info["name"])}: latest synthetic response shares for all study models" loading="lazy"></article>' for key,info in history['states'].items())
    dates = ''.join(f'<option value="{day}">{day}</option>' for day in reversed(history['dates']))
    write(generated/'_states.html',f'<div class="section-toolbar grid-toolbar">{legend()}<label for="overview-date">Snapshot <select id="overview-date"><option value="latest">Latest</option>{dates}</select></label></div><p id="overview-asof" class="source-note">{history["overview"]["latest"]["label"]}</p><div class="state-grid">{cards}</div>')
    features = []
    for f in history['features']:
        metric = history['states']['alabama']['validation'][f['key']]
        features.append(f'<article class="validation-card"><h3>{escape(f["name"])}</h3><img data-feature="{f["key"]}" src="{history['validation_prefix']}/alabama-{f["key"]}.svg" alt="Alabama: {escape(f["name"])} persona shares versus weighted CES reference" loading="lazy"><p data-metric="{f["key"]}">TV {100*metric["tv"]:.1f}% &middot; Largest gap {metric["max_gap_pp"]:.1f} pp</p></article>')
    comparison = validation_comparison_table(history['states']['alabama'], history['features'])
    write(generated/'_validation.html',f'<div class="section-toolbar"><label for="validation-state">State <select id="validation-state">{options(history["states"],"alabama")}</select></label>{legend(True)}</div><p class="source-note">Plots show the 100-draw cohort for the six characteristics displayed below.</p><div class="validation-grid">{"".join(features)}</div><p class="figure-caption">Draw frequencies versus the weighted state CES reference. TV is total variation distance, displayed as a percentage in the plots; pp means percentage points. The table below reports TVD on its 0–1 scale.</p>{comparison}')
    costs=[]
    all_entries=[]
    def usage_cells(cost):
        def amount(field,unknown,money=False):
            value=cost[field]
            if value is None:return 'Unknown'
            formatted=f'${value:.5f}' if money else f'{int(value):,}'
            return ('&ge; ' if cost['partial'] or cost[unknown] else '')+formatted
        attempts=f"{cost['attempts']:,}"
        if cost['partial']:attempts='&ge; '+attempts
        return (f'<td>{attempts}</td><td>{amount("input_tokens","unknown_input_tokens")}</td>'
                f'<td>{amount("output_tokens","unknown_output_tokens")}</td>'
                f'<td>{amount("known_cost","unknown_costs",True)}</td>')
    for key,model in models.items():
        if model.get('kind') == 'external_forecast':
            continue  # Public forecast downloads are not LLM query usage.
        entries=[snapshot['models'][key]['cost'] for snapshot in history['snapshots'].values() if key in snapshot['models']]
        if not entries:
            costs.append(f'<tr><th scope="row">{escape(model["label"])}</th><td colspan="4">Unavailable</td></tr>')
            continue
        all_entries.extend(entries)
        costs.append(f'<tr><th scope="row">{escape(model["label"])}</th>{usage_cells(cumulative_usage(entries))}</tr>')
    total=usage_cells(cumulative_usage(all_entries)) if all_entries else '<td colspan="4">Unavailable</td>'
    write(generated/'_costs.html',f'<table class="cost-table"><caption>Running totals: {history["dates"][0]} through {latest}</caption><thead><tr><th>Model</th><th>Recorded attempts</th><th>Input tokens</th><th>Output tokens</th><th>Reported API cost (USD)</th></tr></thead><tbody>{"".join(costs)}</tbody><tfoot><tr><th scope="row">Total</th>{total}</tr></tfoot></table><p class="source-note">Cumulative usage for the selected source run per model/day across the displayed dates.</p>')
    last_run=max(datetime.fromisoformat(entry['collected_at'])
                 for snapshot in history['snapshots'].values()
                 for entry in snapshot['models'].values()
                 if entry.get('kind') != 'external_forecast').astimezone(ZoneInfo(history['timezone']))
    display_run=(f'{last_run.strftime("%B")} {last_run.day}, {last_run.year}, at '
                 f'{last_run.hour % 12 or 12}:{last_run.minute:02d} {last_run.strftime("%p %Z")}')
    contacts=' and '.join(escape(name) for name in history['contacts'])
    write(generated/'_footer.html',f'<footer class="site-footer"><div><h2>Last run</h2><p><time datetime="{last_run.isoformat()}">{display_run}</time></p></div><div><h2>Contact</h2><p>{contacts}</p><p><a href="https://github.com/JoshECampbell/Senate-Election-Silicon-Sampling">GitHub repository</a></p></div></footer>')
    write(site/'.nojekyll','')
    prune_superseded_figures(site,history)
    print(f'Prepared {len(history["dates"])} dates, {len(models)} configured models, and 35 states. Latest reporting day: {latest}.')
    for day,snapshot in sorted(history['snapshots'].items()):
        print(day, {key:sum(s["eligible"] for s in entry['states'].values()) for key,entry in snapshot['models'].items()})
    cache.save()
    print(f'Figures generated: {cache.built}; reused unchanged: {cache.reused}.')
    return history


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.parse_args()
    prepare()
