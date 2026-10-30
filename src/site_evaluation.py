"""Website components for matched survey validation and full-Senate bootstrap."""
from html import escape
import json

import polars as pl
from site_figures import matched_comparison_figure


def bootstrap_headline(key, model, day, entry):
    value = entry.get('bootstrap_senate')
    if not value:
        return ''
    return (f'<div class="bootstrap-forecast"><h3 class="bootstrap-title">Bootstrap Results</h3>'
            f'<img class="wide-figure" src="figures/{day}/bootstrap/{key}.svg" '
            f'alt="{escape(model["label"])}: 50 display dots summarising {value["resamples"]:,} resampled Senate totals"></div>')


def average_state_comparisons(data):
    """Average state proportions equally; do not pool people or weight by population."""
    eligible = data.filter(pl.col('predicted').is_not_null(), pl.col('actual').is_not_null(),
                           pl.col('eligible_draws') > 0)
    return (eligible.group_by('evaluation', 'model_key', 'option').agg(
        pl.col('predicted').mean(), pl.col('actual').mean(),
        pl.col('eligible_draws').sum(), pl.col('state').n_unique().alias('state_count'))
        .with_columns((100*(pl.col('predicted')-pl.col('actual'))).alias('difference_pp'))
        .sort('evaluation', 'model_key', 'option'))


def matched_validation_section(root, models, site=None):
    folder = root/'data/model_validation'
    manifest_path = folder/'matched_manifest.json'
    if not manifest_path.exists():
        return '<p class="source-note">Matched CES evaluation results have not yet been collected.</p>'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    path = folder/'matched_state_categories.parquet'
    if not path.exists():
        return '<p class="source-note">Matched CES evaluation collection is pending.</p>'
    data = pl.read_parquet(path)
    averages = average_state_comparisons(data)
    average_figures = []
    for name, spec in manifest.items():
        if spec['status'] == 'pending':
            continue
        label = '2026 House intention' if name == 'house' else '2024 presidential vote'
        rows = averages.filter(pl.col('evaluation') == label)
        if rows.is_empty():
            continue
        chart = matched_comparison_figure('Average across states', label, rows.to_dicts(), models, aggregate=True)
        if site is not None:
            relative = f'figures/validation/matched-{name}-average.svg'
            target = site/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(chart, encoding='utf-8')
            chart = f'<img class="wide-figure" src="{relative}" alt="{label}: equal-state average model and CES proportions" loading="lazy">'
        average_figures.append(f'<figure><figcaption>{label}</figcaption>{chart}</figure>')
    if site is not None:
        (site/'data').mkdir(parents=True, exist_ok=True)
        averages.write_parquet(site/'data/evaluation_state_averages.parquet')
    states = sorted(data['state'].unique().to_list())
    options = ''.join(f'<option value="{escape(s, quote=True)}">{escape(s)}</option>' for s in states)
    sections = []
    for state in states:
        tables = []
        for name, spec in manifest.items():
            label = '2026 House intention' if name == 'house' else '2024 presidential vote'
            if spec['status'] == 'pending':
                tables.append(f'<h3>{label}</h3><p>Matching model responses have not yet been collected.</p>')
                continue
            rows = data.filter((pl.col('state') == state) & (pl.col('evaluation') == label))
            content = []
            for row in rows.iter_rows(named=True):
                model = models.get(row['model_key'], {}).get('label', row['model_key'])
                if row['eligible_draws']:
                    cells = (f'<td>{100*row["predicted"]:.1f}%</td><td>{100*row["actual"]:.1f}%</td>'
                             f'<td>{row["difference_pp"]:+.1f} pp</td>')
                else:
                    cells = '<td colspan="3">No eligible survey responses</td>'
                content.append(f'<tr><th scope="row">{escape(model)}</th><td>{escape(row["option"])}</td>'
                               f'{cells}<td>{row["eligible_draws"]}</td></tr>')
            chart = matched_comparison_figure(state, label, rows.to_dicts(), models)
            if site is not None:
                state_slug = state.lower().replace(' ', '-')
                relative = f'figures/validation/matched-{name}-{state_slug}.svg'
                target = site/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(chart, encoding='utf-8')
                chart = f'<img class="wide-figure" src="{relative}" alt="{escape(state)}: {label}, model versus recorded CES shares" loading="lazy">'
            tables.append(f'<section><figure><figcaption>{label}</figcaption>{chart}</figure>'
                          f'<details><summary>Exact values: {label}</summary><table class="cost-table"><caption>{escape(state)}: {label}</caption><thead><tr>'
                          '<th scope="col">Model</th><th scope="col">CES response category</th>'
                          '<th scope="col">Model mean</th><th scope="col">Recorded CES share</th>'
                          '<th scope="col">Difference</th><th scope="col">Eligible draws</th></tr></thead>'
                          f'<tbody>{"".join(content)}</tbody></table></details></section>')
        hidden = ' hidden' if state != states[0] else ''
        sections.append(f'<div data-evaluation-state="{escape(state, quote=True)}"{hidden}><div class="matched-evaluation-grid">{"".join(tables)}</div></div>')
    return ('<p class="source-note">Separate evaluation requests use the manuscript’s House and presidential '
            'questions and response categories.</p>'
            f'<div class="matched-evaluation-grid">{"".join(average_figures)}</div>'
            f'<label for="evaluation-state">State <select id="evaluation-state">{options}</select></label>'
            f'{"".join(sections)}')


def matched_evaluation_costs(root, models):
    """Account for the separately collected evaluation runs without counting draws twice."""
    path = root/'data/model_validation/matched_manifest.json'
    if not path.exists():
        return ''
    rows = []
    usage_path = root/'data/model_validation/matched_usage.json'
    saved_usage = json.loads(usage_path.read_text(encoding='utf-8')) if usage_path.exists() else {}
    for evaluation, spec in json.loads(path.read_text(encoding='utf-8')).items():
        if spec['status'] == 'pending':
            continue
        frame = pl.read_parquet(root/'data/llm_responses'/spec['run']/'results.parquet')
        calls = frame.unique(['model_key', 'state', 'caseid'])
        for (model,), group in calls.group_by('model_key'):
            from site_data import request_usage
            usage = saved_usage.get(evaluation, {}).get(model) or request_usage([], group)
            def amount(field, money=False):
                value = usage[field]
                if value is None:
                    return 'Unknown'
                unknown = {'known_cost': 'unknown_costs', 'input_tokens': 'unknown_input_tokens',
                           'output_tokens': 'unknown_output_tokens'}[field]
                prefix = '&ge; ' if usage['partial'] or usage[unknown] else ''
                return prefix + (f'${value:.5f}' if money else f'{int(value):,}')
            label = models.get(model, {}).get('label', model)
            name = '2026 House intention' if evaluation == 'house' else '2024 presidential vote'
            attempts = ('&ge; ' if usage['partial'] else '') + f'{usage["attempts"]:,}'
            rows.append(f'<tr><th scope="row">{name}</th><td>{escape(label)}</td><td>{attempts}</td>'
                        f'<td>{amount("input_tokens")}</td><td>{amount("output_tokens")}</td>'
                        f'<td>{amount("known_cost", True)}</td></tr>')
    return ('<table class="cost-table"><caption>Separate matched CES evaluation runs</caption>'
            '<thead><tr><th scope="col">Evaluation</th><th scope="col">Model</th>'
            '<th scope="col">Recorded attempts</th><th scope="col">Input tokens</th>'
            '<th scope="col">Output tokens</th><th scope="col">Reported API cost (USD)</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            '<p class="source-note">Evaluation calls are separate from daily Senate collection. Repeated persona '
            'draws share a response and are not extra requests. Where attempt logs were retained, totals include '
            'retries. Partial totals are marked ≥; unavailable token counts are Unknown. The existing '
            'presidential run was reused, not queried again.</p>')
