"""Collect independent daily inputs, archive outcomes, and decide publication.

Workflow: freeze today's Toronto date -> run each model in an isolated job using
config/daily_run.yaml -> save compact retry checkpoints and cumulative usage
-> combine model outputs and the separate polling job -> record what succeeded.
A complete model needs all 35 states with 100 valid sampled rows each. Failed
models are archived but omitted for that day; polling failures preserve history.
Publication requires at least one complete model, verified again by site_data.

Usage (Actions normally supplies the arguments):
  python src/daily_automation.py context
  python src/daily_automation.py model --date 2026-10-28 --model jev
  python src/daily_automation.py poll --date 2026-10-28
  python src/daily_automation.py merge --date 2026-10-28 --run-id 123
  python src/daily_automation.py gate --run-id 123

Collection can incur API charges. Website-only gate/render commands cannot.
Raw logs stay on the collection runner; checkpoints omit prompts and raw bodies.
"""

from argparse import ArgumentParser
from datetime import date, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from helper_query_validation import payload_hash
from polling_forecast import fetch_forecast
from site_data import cumulative_usage, load_history, request_usage


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def output(key, value):
    """Print locally, and expose job outputs when running under GitHub Actions."""
    line = f'{key}={value}'
    print(line)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as file:
            file.write(line + '\n')


def run_name(day):
    day = date.fromisoformat(day)
    month = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')[day.month - 1]
    return f'{month}-{day.day:02d}-no-luna'


def complete_model(metadata):
    states = metadata.get('validation', {}).get('states', [])
    return (len(states) == 35 and len({s['state'] for s in states}) == 35
            and all(s['n'] == 100 and s['n_valid'] == 100 and s['complete'] for s in states))


def collect_model(day, model, root=ROOT):
    settings = yaml.safe_load((root / 'config/daily_run.yaml').read_text())
    if model not in settings['models']:
        raise ValueError(f'Model {model} is not selected for daily collection.')
    folder = root / 'data/llm_responses' / run_name(day) / 'models' / model
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = folder / 'resume.json'
    records = json.loads(checkpoint.read_text()) if checkpoint.exists() else []
    # Feed compact checkpoints through the runner's existing resume/retry logic.
    log = folder / 'responses.jsonl'
    log.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
    args = [sys.executable, str(root / 'src/query_llms.py'), '--run-name', model,
            '--output-root', str(folder.parent), '--models', model]
    for key in ('personas', 'persona_level', 'persona_format', 'prompt_style', 'workers'):
        args.extend(['--' + key.replace('_', '-'), str(settings[key])])
    # A provider failure never prevents another model's job from collecting.
    result = subprocess.run(args, cwd=root, check=False)
    attempts = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    previous_usage = folder / 'usage_summary.json'
    usage = json.loads(previous_usage.read_text()) if previous_usage.exists() else None
    # A first automated run can share a date with an earlier manual run.
    # Preserve that day's already recorded costs instead of replacing them.
    legacy_usage = folder.parents[1] / 'usage_summary.json'
    if usage is None and legacy_usage.exists():
        usage = json.loads(legacy_usage.read_text()).get(model)
    fresh = attempts[len(records):]
    if fresh:
        added = request_usage(fresh, pl.DataFrame())
        usage = cumulative_usage([usage, added]) if usage else added
        write_json(previous_usage, usage)
    elif usage is not None:
        write_json(previous_usage, usage)
    # Keep only latest attempts for resume; historical retry costs are in usage.
    latest = {}
    for record in attempts:
        saved = {k: v for k, v in record.items() if k not in ('payload', 'persona_text', 'response', 'error')}
        saved['payload_sha256'] = payload_hash(record['payload']) if 'payload' in record else record['payload_sha256']
        latest[saved['key']] = saved
    write_json(checkpoint, list(latest.values()))
    metadata_path = folder / 'run_metadata.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    status = {'model': model, 'date': day, 'returncode': result.returncode,
              'complete': result.returncode == 0 and complete_model(metadata)}
    write_json(folder / 'collection_status.json', status)
    print(f'{model}: {"complete" if status["complete"] else "unavailable for publication"}')


def collect_poll(day, root=ROOT):
    success = fetch_forecast(root, expected_date=day)
    stage = root / '.automation/polling'
    write_json(stage / 'status.json', {'date': day, 'success': success})
    if success:
        shutil.copy2(root / 'data/polling_forecast' / f'{day}.json', stage / 'snapshot.json')


def merge(day, run_id, root=ROOT):
    """Combine job artifacts into one dated run, without plotting or rendering."""
    settings = yaml.safe_load((root / 'config/daily_run.yaml').read_text())
    folder = root / 'data/llm_responses' / run_name(day)
    folder.mkdir(parents=True, exist_ok=True)
    successes, usage, statuses, frames, summaries = [], {}, {}, [], []
    for model in settings['models']:
        incoming = root / '.automation/incoming' / f'llm-{model}'
        target = folder / 'models' / model
        target.mkdir(parents=True, exist_ok=True)
        for path in incoming.glob('*'):
            if path.name in ('results.parquet', 'summary.parquet', 'run_metadata.json',
                             'resume.json', 'usage_summary.json', 'collection_status.json'):
                shutil.copy2(path, target / path.name)
        status_file = target / 'collection_status.json'
        status = json.loads(status_file.read_text()) if status_file.exists() else {'complete': False}
        statuses[model] = status
        if status.get('complete'):
            successes.append(model)
        for name, destination in (('results.parquet', frames), ('summary.parquet', summaries)):
            if (target / name).exists():
                destination.append(pl.read_parquet(target / name))
        if (target / 'usage_summary.json').exists():
            usage[model] = json.loads((target / 'usage_summary.json').read_text())
    if frames:
        pl.concat(frames, how='diagonal_relaxed').write_parquet(folder / 'results.parquet')
        pl.concat(summaries, how='diagonal_relaxed').write_parquet(folder / 'summary.parquet')
    write_json(folder / 'run_metadata.json', {'automation': True, 'date': day,
               'published_models': successes, 'models': statuses})
    write_json(folder / 'usage_summary.json', usage)
    polling = root / '.automation/incoming/polling'
    poll_status = json.loads((polling / 'status.json').read_text()) if (polling / 'status.json').exists() else {'success': False}
    if poll_status['success']:
        saved = json.loads((polling / 'snapshot.json').read_text())
        if saved['forecast']['asOf'] != day:
            raise ValueError('Polling artifact does not match the collection date.')
        write_json(root / 'data/polling_forecast' / f'{day}.json', saved)
    write_json(root / 'data/daily_runs' / f'{run_id}.json',
               {'date': day, 'run_name': run_name(day), 'successful_models': successes,
                'polling_success': poll_status['success'], 'source_commit': os.environ.get('GITHUB_SHA')})
    print(f'Archived collection: {day}; complete models: {successes}; fresh polling: {poll_status["success"]}')


def gate(run_id=None, root=ROOT):
    if run_id is None:
        return True  # Main/PR writing and code changes rebuild using saved data.
    status = json.loads((root / 'data/daily_runs' / f'{run_id}.json').read_text())
    if not status['successful_models']:
        print('All models failed; retain the currently published website.')
        return False
    history = load_history(root)  # Independently reconcile draws, IDs and means.
    models = history['snapshots'].get(status['date'], {}).get('models', {})
    return any(models.get(key, {}).get('complete') for key in status['successful_models'])


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['context', 'model', 'poll', 'merge', 'gate'])
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--model')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    day = (args.date or datetime.now(ZoneInfo('America/Toronto')).date()).isoformat()
    if args.command == 'context':
        output('date', day)
        output('run_name', run_name(day))
        output('models', json.dumps(yaml.safe_load((ROOT / 'config/daily_run.yaml').read_text())['models']))
    elif args.command == 'model':
        collect_model(day, args.model)
    elif args.command == 'poll':
        collect_poll(day)
    elif args.command == 'merge':
        merge(day, args.run_id)
    else:
        output('publish', str(gate(args.run_id)).lower())
