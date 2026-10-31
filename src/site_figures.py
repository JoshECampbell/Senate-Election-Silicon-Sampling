"""Standalone editorial SVG figures built from an already verified site snapshot.

Workflow: receive prepared chart records -> draw SVG marks and labels -> return
SVG text for the preparation script to save.
Usage: imported by src/prepare_website.py; no standalone command.

These functions do not read data or contact APIs. SVG files are independently
viewable and are embedded by Quarto/loaded by the small selector controller.
Draw observed reporting dates only. Model shapes and line styles come from the
website config and stay fixed when models are hidden in the browser.
"""

from html import escape
from datetime import date
import textwrap

from site_data import CATEGORIES, SEAT_CATEGORIES


PAPER = "#FAF9F6"
INK = "#181817"
MUTED = "#62615D"
RULE = "#D9D6CE"


def text(x, y, value, *, size=13, fill=INK, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(value))}</text>')


def line(x1, y1, x2, y2, color=RULE, width=1):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>'


def rect(x, y, width, height, fill, title=""):
    return (f'<rect x="{x:.3f}" y="{y:.3f}" width="{max(0,width):.3f}" height="{height:.3f}" fill="{fill}">'
            f'<title>{escape(title)}</title></rect>')


def svg(width, height, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{escape(title, quote=True)}"><title>{escape(title)}</title>'
            '<style>text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif}</style>'
            f'<rect width="{width}" height="{height}" fill="{PAPER}"/>{body}</svg>')


def marker(shape, x, y, radius, colour, css_class, title, opacity=1):
    """A model's shape carries identity; category colour carries response type."""
    attrs = f'class="{css_class}" fill="{colour}" fill-opacity="{opacity}"'
    if css_class == 'mean-dot':
        attrs += f' stroke="{INK}" stroke-width="1"'
    tooltip = f'<title>{escape(title)}</title>'
    if shape == 'diamond':
        coords = f'{x:.3f},{y-radius:.3f} {x+radius:.3f},{y:.3f} {x:.3f},{y+radius:.3f} {x-radius:.3f},{y:.3f}'
        return f'<polygon {attrs} points="{coords}">{tooltip}</polygon>'
    if shape == 'triangle':
        coords = f'{x:.3f},{y-radius:.3f} {x-radius:.3f},{y+radius:.3f} {x+radius:.3f},{y+radius:.3f}'
        return f'<polygon {attrs} points="{coords}">{tooltip}</polygon>'
    if shape == 'square':
        return f'<rect {attrs} x="{x-radius:.3f}" y="{y-radius:.3f}" width="{radius*2}" height="{radius*2}">{tooltip}</rect>'
    return f'<circle {attrs} cx="{x:.3f}" cy="{y:.3f}" r="{radius}">{tooltip}</circle>'


def response_figure(state_key, history, column, through_date):
    """All observed model/day clouds, with exact y values and calendar-date x.

    Each eligible cloud contains 100 sampled rows. Repeated respondents remain
    repeated marks. Horizontal jitter is stable across panels; no vertical jitter
    or interpolated observations. A missing model/day breaks the mean line.
    """
    state = history['states'][state_key]['name']
    days = [d for d in history['dates'] if d<=through_date]
    _, label, colour = next(c for c in CATEGORIES if c[0]==column)
    left, right, top, bottom = 52, 428, 36, 228
    first, last = (date.fromisoformat(d).toordinal() for d in (days[0],days[-1]))
    def xpos(day):
        ordinal = date.fromisoformat(day).toordinal()
        return 240 if first==last else left+48+(ordinal-first)/(last-first)*(right-left-96)
    body = [text(left,20,label,size=17,fill=colour if column!='p_would_not_vote' else MUTED,weight='bold')]
    for share in (0.,.5,1.):
        y = bottom-share*(bottom-top)
        body.extend([line(left,y,right,y),text(left-8,y+4,f'{share*100:.0f}%',size=15,fill=MUTED,anchor='end')])
    body.append(line(left,bottom,right,bottom,INK))
    ticks = sorted({round(i*(len(days)-1)/min(4,len(days)-1)) for i in range(min(5,len(days)))}) if len(days)>1 else [0]
    for i in ticks:
        x = xpos(days[i])
        body.extend([line(x,bottom,x,bottom+5,INK),text(x,bottom+24,days[i][5:],size=15,fill=MUTED,anchor='middle')])
    body.append(text(right,280,days[-1][:4],size=12,fill=MUTED,anchor='end'))
    for model_index,(key,model) in enumerate(history['models'].items()):
        body.append(f'<g data-model="{escape(key)}">')
        previous = None
        for day in days:
            entry = history['snapshots'][day]['models'].get(key)
            values = entry['states'][state_key] if entry else None
            if not values or not values['eligible'] or values['means'][column] is None:
                previous = None
                continue
            x = xpos(day)+(model_index-1)*14
            mean_y = bottom-values['means'][column]*(bottom-top)
            ordinal = date.fromisoformat(day).toordinal()
            if previous and ordinal-previous[0]==1:
                body.append(f'<path d="M {previous[1]:.3f} {previous[2]:.3f} L {x:.3f} {mean_y:.3f}" fill="none" stroke="{colour}" stroke-width="2" stroke-dasharray="{model["dash"]}"/>')
            for point in values['points']:
                jitter = (((point['draw']*.61803398875)%1)-.5)*32
                y = bottom-point[column]*(bottom-top)
                title = f'{model["label"]}; {state}; {day}; sampled draw {point["draw"]}; {100*point[column]:.2f}%. Repeated draws may share a response.'
                body.append(marker(model['shape'],x+jitter,y,3,colour,'persona-dot',title,.16))
            title = (f'{model["label"]}; {day}; collected {entry["collected_at"]}; '
                     f'{100*values["means"][column]:.2f}%; ')
            if model.get('kind') == 'external_forecast':
                title += 'Implied two-candidate forecast share; not a measured polling share.'
                if entry.get('carried_forward'):
                    title += f' * Reused forecast from {entry["source_date"]}.'
                    body.append(text(x+8, mean_y-5, '*', size=14, fill=INK))
            else:
                title += (f'{entry["model_id"]}; snapshot {", ".join(entry["model_snapshots"])}; '
                          f'{values["valid"]}/100 valid sampled draws; {values["unique"]} unique respondents.')
            body.append(marker(model['shape'],x,mean_y,6.5,colour,'mean-dot',title))
            previous = (ordinal,x,mean_y)
        body.append('</g>')
    return svg(450,285,f'{state}: {label} synthetic probabilities and implied forecast shares, {days[0]} to {through_date}.', ''.join(body))


def state_figure(state, records, models):
    """One four-category bar per study model; missing rows stay labelled gaps."""
    body = []
    for index,(key,model) in enumerate(models.items()):
        y = index*43
        values = records.get(key)
        body.append(text(0,y+17,model['label'],size=12 if model.get('kind') else 14))
        body.append(text(0,y+33,values['date'] if values else 'Unavailable',size=11,fill=MUTED))
        if not values or not values['eligible']:
            body.append(text(106,y+20,'Unavailable',size=13,fill=MUTED))
            continue
        x = 106.
        for column,label,colour in CATEGORIES:
            if values['means'][column] is None:
                continue
            width = values['means'][column]*224
            basis = ('implied two-candidate share' + (f'; reused from {values["source_date"]}' if values.get('source_date') else '')) if model.get('kind') else '100/100 valid'
            body.append(rect(x,y+5,width,16,colour,f'{model["label"]}; {values["date"]}; {label}: {100*values["means"][column]:.2f}%; {basis}.'))
            x += width
    bottom = 43*len(models)
    body.extend([text(106,bottom+7,'0%',size=12,fill=MUTED),text(330,bottom+7,'100%',size=12,fill=MUTED,anchor='end')])
    return svg(340,bottom+13,f'{state}: synthetic response shares and implied two-candidate forecast shares; unavailable rows are not zeros.', ''.join(body))


def senate_figure(senate):
    """Full chamber, solid party colours; fixed and contested seats look alike."""
    body, x = [], 0.
    # Put independent seats between the parties, so the red segment does not
    # inherit a misleading left-to-right cumulative "51 seats" reference line.
    by_key={row[0]:row for row in SEAT_CATEGORIES}
    for key in ('democrat','independent','republican'):
        _,label,_,colour=by_key[key]
        total = senate['totals'][key]
        body.append(rect(x,35,total*9,26,colour,f'{label}: {total} seats'))
        x += total*9
    unallocated = senate['totals']['unallocated']
    if unallocated:
        body.append(f'<rect x="{x}" y="35" width="{unallocated*9}" height="26" fill="{PAPER}" stroke="{INK}"><title>{unallocated} unallocated seats</title></rect>')
    totals = senate['totals']
    title = f'100-seat Senate projection: {totals["democrat"]} Democratic, {totals["republican"]} Republican, {totals["independent"]} independent/other, {unallocated} unallocated.'
    return svg(900,70,title,''.join(body))


def matched_comparison_figure(state, evaluation, rows, models, aggregate=False):
    """Paired dots compare model category means with matched recorded CES shares."""
    left, right = 148, 490
    body = [text(12, 22, state, size=17, weight='600'),
            text(left, 43, '○ Recorded CES    ● Model', size=12, fill=MUTED)]
    groups = {}
    for row in rows:
        groups.setdefault(row['option'], []).append(row)
    y = 68
    for option, records in groups.items():
        body.append(text(12, y, option, size=14, weight='600'))
        y += 22
        for row in sorted(records, key=lambda r: r['model_key']):
            label = models.get(row['model_key'], {}).get('label', row['model_key'])
            body.append(text(12, y+4, label, size=12, fill=MUTED))
            if row['eligible_draws']:
                actual = left + row['actual']*(right-left)
                predicted = left + row['predicted']*(right-left)
                title = (f'{label}; {option}; model {100*row["predicted"]:.1f}%; '
                         f'CES {100*row["actual"]:.1f}%; {row["difference_pp"]:+.1f} pp; '
                         f'{row["eligible_draws"]} eligible draws')
                if aggregate:
                    title += f'; equal weight across {row["state_count"]} states'
                body.append(line(actual, y, predicted, y, RULE, 2))
                body.append(f'<circle class="ces-reference-dot" cx="{actual:.3f}" cy="{y}" r="4" '
                            f'fill="{PAPER}" stroke="{MUTED}" stroke-width="1.5"><title>{escape(title)}</title></circle>')
                body.append(marker('circle', predicted, y, 4, INK, 'matched-model-dot', title))
                body.append(text(506, y+4, f'{row["difference_pp"]:+.1f} pp', size=12))
            else:
                body.append(text(left, y+4, 'No eligible survey responses', size=12, fill=MUTED))
            y += 23
        y += 13
    bottom = y+2
    for share in (0, .25, .5, .75, 1):
        x = left + share*(right-left)
        body.append(line(x, 53, x, bottom, RULE, .6))
        body.append(text(x, bottom+21, f'{100*share:.0f}%', size=12, anchor='middle'))
    body.append(line(left, bottom, right, bottom, INK))
    axis_label = 'Mean category share; equal state weight' if aggregate else 'Share of eligible persona draws'
    body.append(text((left+right)/2, bottom+43, axis_label, size=12, anchor='middle'))
    return svg(580, bottom+55, f'{state}: {evaluation}; paired model and recorded CES category proportions.', ''.join(body))


def bootstrap_seat_dot_figure(label, totals, classic=None, summary=None):
    """Fifty display dots summarise all replicates: 25 dots per party.

    Largest-remainder allocation rounds each party's histogram to 25 dots.
    Dot counts are a display approximation; all 10,000 replicates determine SE.
    """
    from collections import Counter
    import math
    classic, summary = classic or {}, summary or {}
    colours = {'democrat': '#326A9D', 'republican': '#BD4942'}
    names = {'democrat': 'Democrats', 'republican': 'Republicans',
             'independent': 'Independent / other', 'unallocated': 'Unallocated'}
    body = []
    y = 20
    for party in names:
        if party not in classic:
            continue
        if party == 'unallocated' and not classic[party] and not summary.get(party, {}).get('mean'):
            continue
        error = summary.get(party, {}).get('sem')
        estimate = str(classic[party]) + (f' \u00b1 {error:.2f}' if error is not None else '')
        body.append(text(450, y, f'{names[party]}: {estimate} seats', size=10,
                         fill=colours.get(party, MUTED), weight='600', anchor='end'))
        y += 14
    display = {}
    for party, values in totals.items():
        if not values:
            raise ValueError('Cannot plot an empty bootstrap distribution.')
        counts = Counter(values)
        quotas = {seat: 25*count/len(values) for seat, count in counts.items()}
        allocation = {seat: math.floor(q) for seat, q in quotas.items()}
        remaining = 25-sum(allocation.values())
        for seat in sorted(counts, key=lambda n: (-(quotas[n]-allocation[n]), n))[:remaining]:
            allocation[seat] += 1
        display[party] = (counts, allocation)
    minimum = min(min(values) for values in totals.values())-1
    maximum = max(max(values) for values in totals.values())+1
    left, right = 30, 450
    peak = max(max(allocation.values()) for _, allocation in display.values())
    bottom = max(82, y+14) + peak*5.5
    for party, (counts, allocation) in display.items():
        body.append(f'<g class="bootstrap-seat-stack" data-party="{party}" data-resamples="{len(totals[party])}" data-display-count="25">')
        for seats, count in sorted(allocation.items()):
            x = left+(seats-minimum)/(maximum-minimum)*(right-left)
            x += -2.5 if party == 'democrat' else 2.5
            for level in range(count):
                yy = bottom-4-level*5.5
                title = (f'{names[party]}: {seats} seats; {counts[seats]:,} of '
                         f'{len(totals[party]):,} resamples ({100*counts[seats]/len(totals[party]):.2f}%). '
                         'Display rounded to 25 dots per party.')
                body.append(marker('circle', x, yy, 2.15, colours[party], 'bootstrap-summary-dot', title))
        body.append('</g>')
    body.append(line(left, bottom+3, right, bottom+3, INK))
    step = max(1, math.ceil((maximum-minimum)/9))
    for seats in range(minimum, maximum+1):
        x = left+(seats-minimum)/(maximum-minimum)*(right-left)
        body.append(line(x, bottom+3, x, bottom+8, INK))
        if (seats-minimum)%step == 0 or seats == maximum:
            body.append(text(x, bottom+23, seats, size=11, anchor='middle'))
    body.append(text(240, bottom+42, 'Senate Seats', size=12, anchor='middle'))
    return svg(480, bottom+53, f'{label}: 50 stacked display dots summarising Democratic and Republican bootstrap seat distributions.', ''.join(body))


def seat_distribution_figure(seats, label):
    """Share of bootstrap resamples by Democratic seat count, coloured by control.

    Independents stay unassigned, so a Republican majority needs 51 Republican
    seats, i.e. at most 49 - independents Democratic seats.
    """
    counts = {int(k): v for k, v in seats['histogram'].items()}
    draws = sum(counts.values())
    low, high = min(counts) - 1, max(counts) + 1
    left, right, top, bottom = 40, 880, 14, 118
    step = (right-left)/(high-low+1)
    peak = max(counts.values())/draws
    rep_max = 100 - 51 - seats['independent_seats']
    body = [line(left, bottom, right, bottom, INK)]
    for seat in range(low, high+1):
        share = counts.get(seat, 0)/draws
        colour = '#326A9D' if seat >= 51 else '#BD4942' if seat <= rep_max else '#777777'
        x = left+(seat-low)*step
        height = share/peak*(bottom-top) if peak else 0
        body.append(rect(x+1, bottom-height, step-2, height, colour,
                         f'{seat} Democratic seats: {100*share:.1f}% of {draws:,} bootstrap resamples'))
        if seat % 5 == 0:
            body.append(text(x+step/2, bottom+18, seat, size=13, fill=MUTED, anchor='middle'))
    body.append(text(left, bottom+34, 'Democratic seats', size=12, fill=MUTED))
    title = (f'{label}: Democratic seats across {draws:,} bootstrap resamples of the personas; '
             f'median {seats["median"]}, 90% range {seats["low"]}–{seats["high"]}.')
    return svg(900, 160, title, ''.join(body))


def share_axes(left, right, top, bottom, x_label, y_label):
    """Square 0-100% axes with quarter gridlines, shared by the validation plots."""
    body = []
    for share in (0, .25, .5, .75, 1):
        x = left+share*(right-left)
        y = bottom-share*(bottom-top)
        body.extend([line(left, y, right, y), line(x, top, x, bottom),
                     text(left-6, y+4, f'{share*100:.0f}%', size=12, fill=MUTED, anchor='end'),
                     text(x, bottom+16, f'{share*100:.0f}%', size=12, fill=MUTED, anchor='middle')])
    body.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{top}" stroke="{MUTED}" '
                'stroke-width="1.5" stroke-dasharray="5 4"/>')
    body.extend([text((left+right)/2, bottom+34, x_label, size=12, fill=MUTED, anchor='middle'),
                 f'<text x="14" y="{(top+bottom)/2}" font-size="12" fill="{MUTED}" text-anchor="middle" '
                 f'transform="rotate(-90 14 {(top+bottom)/2})">{escape(y_label)}</text>'])
    return body


def backcast_figure(label, rows):
    """One model's 2024 back-cast: each state's model share against the result.

    The dashed diagonal is where a perfect model would sit.
    """
    left, right, top, bottom = 52, 332, 12, 292
    scale = right-left
    body = share_axes(left, right, top, bottom, "Model's Harris share", 'Actual Harris share')
    for row in rows:
        x, y = left+row['predicted_two_party']*scale, bottom-row['actual_two_party']*scale
        title = (f'{row["state"]}: model {100*row["predicted_two_party"]:.1f}%, actual '
                 f'{100*row["actual_two_party"]:.1f}%')
        body.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#326A9D" fill-opacity=".75"><title>{escape(title)}</title></circle>')
    title = f'{label}: 2024 back-cast Harris share against the official result in {len(rows)} states.'
    return svg(345, 335, title, ''.join(body))


def error_figure(label, rows):
    """Each state's back-cast error, with states ordered by the official result."""
    rows = sorted(rows, key=lambda r: r['actual_two_party'])
    left, right, top = 112, 330, 26
    step = 14
    bottom = top+step*len(rows)
    limit = 40
    def xpos(points):
        return left+(max(-limit, min(limit, points))+limit)/(2*limit)*(right-left)
    body = [text(left-104, 14, 'Most Republican state first', size=11, fill=MUTED)]
    for points in (-40, -20, 0, 20, 40):
        x = xpos(points)
        body.extend([line(x, top-6, x, bottom, INK if points == 0 else RULE),
                     text(x, bottom+16, f'{points:+d}' if points else '0', size=12, fill=MUTED, anchor='middle')])
    for index, row in enumerate(rows):
        y = top+index*step+step/2
        error = 100*row['error']
        body.extend([text(left-8, y+4, row['state'], size=11, anchor='end'),
                     line(xpos(0), y, xpos(error), y, RULE, 2),
                     f'<circle cx="{xpos(error):.2f}" cy="{y:.2f}" r="4" fill="{INK}">'
                     f'<title>{escape(row["state"])}: error {error:+.1f} points</title></circle>'])
    body.append(text((left+right)/2, bottom+34, 'Error in Harris share (points)', size=12, fill=MUTED, anchor='middle'))
    return svg(345, bottom+44, f"{label}: each state's 2024 back-cast error against the official result.", ''.join(body))


def calibration_figure(rows, models):
    """Predicted against actual P(Democrat | two-party), one series per model."""
    left, right, top, bottom = 52, 332, 12, 292
    scale = right-left
    body = share_axes(left, right, top, bottom, 'Predicted chance of Democrat', 'Share who intend Democrat')
    for key, model in models.items():
        points = sorted((r for r in rows if r['model_key'] == key), key=lambda r: r['predicted'])
        if not points:
            continue
        coords = [(left+r['predicted']*scale, bottom-r['actual']*scale) for r in points]
        body.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in coords)}" fill="none" '
                    f'stroke="{INK}" stroke-width="1.5" stroke-dasharray="{model["dash"]}"/>')
        for (x, y), r in zip(coords, points):
            title = (f'{model["label"]}: predicted {100*r["predicted"]:.0f}%, actual {100*r["actual"]:.0f}% '
                     f'({r["n"]:,} persona rows)')
            body.append(marker(model['shape'], x, y, 4.5, INK, 'calibration-dot', title))
    return svg(345, 335, 'Calibration: predicted chance of a Democratic vote against the share of personas who intend '
               'to vote Democratic, by model.', ''.join(body))


def validation_figure(state, feature, data):
    """Preserve every saved category, including absent and missing-response groups."""
    categories = data["categories"]
    row_height = 46
    height = len(categories)*row_height+50
    left, width = 210, 168
    body = []
    for share in (0., .5, 1.):
        x = left+share*width
        body.extend([line(x,4,x,height-34),text(x,height-12,f'{100*share:.0f}%',size=15,fill=MUTED,anchor="middle")])
    for index, row in enumerate(categories):
        cy = index*row_height+22
        labels = textwrap.wrap(row["category"],width=23,break_long_words=False) or [row["category"]]
        for j, label in enumerate(labels):
            body.append(text(2,cy+(j-(len(labels)-1)/2)*16+4,label,size=15))
        for offset, source, colour in ((-8,"persona_share","#326A9D"),(2,"reference_share","#343434")):
            title = f'{row["category"]}; {"Persona draws" if source=="persona_share" else "Weighted CES reference"}: {100*row[source]:.2f}%; difference {row["difference_pp"]:+.2f} percentage points.'
            body.append(rect(left,cy+offset,row[source]*width,7,colour,title))
    return svg(400,height,f'{state}, {feature}: persona shares versus weighted CES reference, all {len(categories)} categories.',"".join(body))
