"""Standalone editorial SVG figures built from an already verified site snapshot.

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
            if not values or not values['eligible']:
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
            title = (f'{model["label"]}; {entry["model_id"]}; snapshot {", ".join(entry["model_snapshots"])}; '
                     f'{day}; collected {entry["collected_at"]}; mean {100*values["means"][column]:.2f}%; '
                     f'{values["valid"]}/100 valid sampled draws; {values["unique"]} unique respondents.')
            body.append(marker(model['shape'],x,mean_y,6.5,colour,'mean-dot',title))
            previous = (ordinal,x,mean_y)
        body.append('</g>')
    return svg(450,285,f'{state}: {label} synthetic probabilities, {days[0]} to {through_date}.', ''.join(body))


def state_figure(state, records, models):
    """One four-category bar per study model; missing rows stay labelled gaps."""
    body = []
    for index,(key,model) in enumerate(models.items()):
        y = index*43
        values = records.get(key)
        body.append(text(0,y+17,model['label'],size=14))
        body.append(text(0,y+33,values['date'] if values else 'Unavailable',size=11,fill=MUTED))
        if not values or not values['eligible']:
            body.append(text(106,y+20,'Unavailable',size=13,fill=MUTED))
            continue
        x = 106.
        for column,label,colour in CATEGORIES:
            width = values['means'][column]*224
            body.append(rect(x,y+5,width,16,colour,f'{model["label"]}; {values["date"]}; {label}: {100*values["means"][column]:.2f}%; 100/100 valid.'))
            x += width
    bottom = 43*len(models)
    body.extend([text(106,bottom+7,'0%',size=12,fill=MUTED),text(330,bottom+7,'100%',size=12,fill=MUTED,anchor='end')])
    return svg(340,bottom+13,f'{state}: synthetic response shares by model; unavailable rows are not zeros.', ''.join(body))


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
