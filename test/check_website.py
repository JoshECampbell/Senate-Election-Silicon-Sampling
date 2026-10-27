"""Tests run:
- Check rendered HTML anchors, unique IDs and portable local asset paths.
- Check 35-state coverage, 100-seat totals and complete synthetic samples.
- Count persona dots and check state/validation figures for every prepared date.
- Reject private respondent fields or request logs in the public website bundle.

Usage (after rendering): uv run python test/check_website.py
"""

from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.resources = [], []
        self.state_cards = self.validation_cards = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag in ("img", "script") and attrs.get("src"):
            self.resources.append(attrs["src"])
        if tag == "link" and attrs.get("href"):
            self.resources.append(attrs["href"])
        if tag == "article":
            self.state_cards += "state-card" in attrs.get("class", "").split()
            self.validation_cards += "validation-card" in attrs.get("class", "").split()


def check_site(site):
    site = site.resolve()
    page = Page()
    page.feed((site / "index.html").read_text(encoding="utf-8"))
    duplicates = [name for name, count in Counter(page.ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate HTML IDs: {duplicates}")
    if not {"results", "methods", "discussion", "costs"}.issubset(page.ids):
        raise ValueError("Required section anchors are missing.")
    for resource in [*page.resources, "data/history.json", ".nojekyll"]:
        url = urlsplit(resource)
        if url.scheme or url.netloc:
            continue
        if url.path.startswith("/"):
            raise ValueError(f"Root-relative asset breaks repository-subpath hosting: {resource}")
        path = (site / unquote(url.path)).resolve()
        if not path.is_relative_to(site) or not path.is_file():
            raise ValueError(f"Missing or out-of-bundle resource: {resource}")
    snapshot = json.loads((site / "data/history.json").read_text(encoding="utf-8"))
    if page.state_cards != 35 or page.validation_cards != len(snapshot["features"]):
        raise ValueError("State/validation chart coverage does not match the prepared data.")
    for day in snapshot['dates']:
        daily_path=site/'data'/day/'snapshot.json'
        daily=json.loads(daily_path.read_text(encoding='utf-8'))
        for key,entry in daily['snapshots'][day]['models'].items():
            if entry['senate'] and sum(entry['senate']['totals'].values())!=100:
                raise ValueError(f'{day}/{key}: Senate total differs from 100.')
            for state in entry['states'].values():
                if entry.get('kind') != 'external_forecast' and state['eligible'] and (state['valid']!=100 or len(state['points'])!=100):
                    raise ValueError('An incomplete sample was published.')
        for state in snapshot['states']:
            if day==snapshot['date']:
                for column in ('p_democrat','p_republican','p_third_party','p_would_not_vote'):
                    path=site/f'figures/{day}/responses/{state}-{column}.svg'
                    root=ET.fromstring(path.read_text(encoding='utf-8'))
                    # Each dated response plot contains observed history through its
                    # as-of day. Every eligible state/model/day contributes 100 dots.
                    expected=sum(100 for d in snapshot['dates'] if d<=day
                                 for entry in snapshot['snapshots'][d]['models'].values()
                                 if entry.get('kind') != 'external_forecast' and entry['states'][state]['eligible'])
                    count=sum(n.get('class')=='persona-dot' for n in root.iter())
                    if count!=expected:
                        raise ValueError(f'{path}: expected {expected} dots, found {count}.')
            for selection in (day,'latest'):
                path=site/(snapshot['overview'][selection]['prefix']+f'/{state}.svg')
                content=path.read_text(encoding='utf-8')
                for model in snapshot['models'].values():
                    if model['label'] not in content:
                        raise ValueError(f'{path}: missing model row {model["label"]}.')
            for feature in snapshot['features']:
                path=site/snapshot['validation_prefix']/f'{state}-{feature["key"]}.svg'
                ET.fromstring(path.read_text(encoding='utf-8'))
    # Public exports include anonymous draw numbers and provider IDs, never raw
    # respondent IDs, complete prompt text or the append-only request logs.
    for path in (site/'data').rglob('*.json'):
        text=path.read_text(encoding='utf-8')
        if '"caseid"' in text or '"persona_text"' in text or '"payload"' in text:
            raise ValueError(f'Private source fields found in {path}.')
    if (site / ".env").exists() or (site / "responses.jsonl").exists():
        raise ValueError("Private source files must not appear in the public bundle.")
    return snapshot


if __name__ == "__main__":
    snapshot = check_site(ROOT / "docs")
    print(f'Pages bundle verified: {len(snapshot["dates"])} dates, {len(snapshot["models"])} models, 35 states, {len(snapshot["features"])} validation fields, all persona dots, and portable local assets.')
