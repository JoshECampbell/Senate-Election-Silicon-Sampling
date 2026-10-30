"""Collect and score matched CES evaluation requests, separately from Senate runs.

Usage: python src/validate_electoral_responses.py [--collect] [--evaluations house president]
Without --collect no provider calls are made. Missing runs are reported as pending.
Question wording and the grouped presidential choices follow the manuscript.
"""
from argparse import ArgumentParser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'src'))
from src.query_llms import build_jobs, load_personas, load_value_labels, slug
from src.create_personas import SENATE_STATES_2026

MODELS = ['jev', 'mercury', 'decider']
SPECS = {
    'house': {'label': '2026 House intention', 'config': 'validation_house_2026.yaml',
              'run': 'validation-house-2026', 'field': 'CC25_363',
              'mapping': {1: 'Would not vote', 2: 'Democrat', 3: 'Republican', 4: 'Not sure'}},
    'president': {'label': '2024 presidential vote', 'config': 'validation_president_2024.yaml',
                  'run': 'validation-president-2024', 'field': 'presvote24post',
                  'mapping': {1: 'Democrat', 2: 'Republican', 3: 'Third party', 4: 'Third party',
                              5: 'Third party', 6: 'Third party', 8: 'Third party', 9: 'Would not vote'}}}


def expected_jobs(root, config):
    args = type('Selection', (), {'models': MODELS, 'persona_level': [9],
                'persona_format': ['sentence'], 'prompt_style': ['role_play'], 'news_file': None})()
    return build_jobs(load_personas(root/'data/personas/sample_100', None, None),
                      config, load_value_labels(root/'config/ces_codes/ces25_value_labels.yaml'), args)


def verify_run(results, metadata, config, root):
    """Reject wrong questions/settings/cohorts before attributing any validation.

    Saved metadata names the request configuration. Compare its relevant fields
    with the intended request, then reconcile each response's persona and row IDs.
    """
    if not metadata.get('invocations'):
        raise ValueError('Missing request provenance.')
    for invocation in metadata['invocations']:
        args = invocation['args']
        source = Path(args['config'])
        source = source if source.is_absolute() else root/source
        if not source.exists():
            source = root/'config'/source.name
        old = yaml.safe_load(source.read_text(encoding='utf-8'))
        for field in ('election', 'options', 'persona_levels', 'display_names'):
            if old[field] != config[field]:
                raise ValueError(f'Recorded request does not match intended evaluation: {field}.')
        old_prompt, new_prompt = old['prompt_styles']['role_play'], config['prompt_styles']['role_play']
        if old_prompt['context'] != new_prompt['context']:
            raise ValueError('Recorded persona template does not match.')
        for state in SENATE_STATES_2026.values():
            if old_prompt['question'].format(state=state, **old['election']) != new_prompt['question'].format(state=state, **config['election']):
                raise ValueError('Recorded electoral question does not match.')
        if (args.get('persona_level') != [9] or args.get('persona_format') != ['sentence']
                or args.get('prompt_style') != ['role_play'] or args.get('news_file')):
            raise ValueError('Evaluation must use nine-characteristic sentence role-play with no news.')
        for key in MODELS:
            if old['models'][key] != config['models'][key]:
                raise ValueError('Model request configuration differs.')
    jobs = expected_jobs(root, config)
    expected = {(j['model_key'], j['state'], j['caseid']): j for j in jobs}
    required = ['model_key', 'state', 'caseid', 'persona_row', 'model', 'persona_text',
                'persona_level', 'persona_format', 'prompt_style', 'news', 'probability_valid',
                'CC25_363', 'presvote24post', *[slug(o) for o in config['options']]]
    if not set(required).issubset(results.columns):
        raise ValueError('Missing evaluation fields or requested response options.')
    seen = set()
    for row in results.iter_rows(named=True):
        identity = (row['model_key'], row['state'], row['caseid'])
        job = expected.get(identity)
        position = (row['model_key'], row['state'], row['persona_row'])
        if not job or position in seen or row['persona_row'] not in job['persona_rows']:
            raise ValueError('Missing, duplicate or unexpected respondent/draw position.')
        seen.add(position)
        for field in ('model', 'persona_text', 'persona_level', 'persona_format', 'prompt_style',
                      'news', 'CC25_363', 'presvote24post'):
            if row[field] != job[field]:
                raise ValueError(f'Evaluation response differs from source persona: {field}.')
    expected_positions = {(j['model_key'], j['state'], p) for j in jobs for p in j['persona_rows']}
    if seen != expected_positions or len(seen) != 100 * 35 * len(MODELS):
        raise ValueError('Expected all 100 original draw positions in all 35 states for each model.')


def score_categories(results, spec, options):
    """Same eligible draws on both sides; repeated source respondents retain multiplicity."""
    rows, coverage = [], []
    columns = [slug(o) for o in options]
    for (model, state), group in results.group_by('model_key', 'state'):
        eligible = group.filter(pl.col('probability_valid'), pl.col(spec['field']).is_in(list(spec['mapping'])))
        values = eligible.select(columns).to_numpy()
        if values.size and (not np.isfinite(values).all() or (values < 0).any()
                            or (values > 1).any() or (np.abs(values.sum(axis=1)-1) > 1e-6).any()):
            raise ValueError('A response marked valid has invalid probabilities.')
        target = [spec['mapping'][v] for v in eligible[spec['field']].to_list()]
        coverage.append({'evaluation': spec['label'], 'model_key': model, 'state': state,
                         'draws': group.height, 'valid_responses': int(group['probability_valid'].sum()),
                         'eligible_draws': eligible.height,
                         'missing_survey_draws': group.filter(~pl.col(spec['field']).is_in(list(spec['mapping'])).fill_null(False)).height})
        for option, column in zip(options, columns):
            predicted = float(eligible[column].mean()) if eligible.height else None
            actual = target.count(option)/len(target) if target else None
            rows.append({'evaluation': spec['label'], 'model_key': model, 'state': state,
                         'option': option, 'eligible_draws': eligible.height,
                         'predicted': predicted, 'actual': actual,
                         'difference_pp': 100*(predicted-actual) if actual is not None else None})
    return pl.DataFrame(rows), pl.DataFrame(coverage)


def collect_and_score(root=ROOT, collect=False, evaluations=None):
    out = root/'data/model_validation'
    out.mkdir(parents=True, exist_ok=True)
    previous_manifest = json.loads((out/'matched_manifest.json').read_text(encoding='utf-8')) if (out/'matched_manifest.json').exists() else {}
    previous_usage = json.loads((out/'matched_usage.json').read_text(encoding='utf-8')) if (out/'matched_usage.json').exists() else {}
    tables, coverage, manifest = [], [], {}
    for name in evaluations or SPECS:
        spec = SPECS[name]
        config_path = root/'config'/spec['config']
        config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        run = root/'data/llm_responses'/spec['run']
        # Reuse the already-collected presidential run only after checking its
        # recorded configuration and every saved source persona/draw identity.
        legacy = root/'data/llm_responses/backcast-2024'
        source = run
        if name == 'president' and not (run/'results.parquet').exists() and (legacy/'results.parquet').exists():
            try:
                verify_run(pl.read_parquet(legacy/'results.parquet'),
                           json.loads((legacy/'run_metadata.json').read_text()), config, root)
                source = legacy
            except (ValueError, KeyError, OSError):
                source = run
        if collect and source == run:
            run.mkdir(parents=True, exist_ok=True)
            request_snapshot = run/'evaluation_request.json'
            if request_snapshot.exists():
                if json.loads(request_snapshot.read_text(encoding='utf-8')) != config:
                    raise ValueError('Evaluation configuration changed; use a new run name.')
            else:
                request_snapshot.write_text(json.dumps(config, indent=2), encoding='utf-8')
            command = [sys.executable, str(root/'src/query_llms.py'), '--config', str(config_path),
                       '--run-name', spec['run'], '--personas', 'data/personas/sample_100',
                       '--models', *MODELS, '--persona-level', '9', '--persona-format', 'sentence',
                       '--prompt-style', 'role_play']
            subprocess.run(command, cwd=root, check=True,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        if not (source/'results.parquet').exists():
            manifest[name] = {'status': 'pending', 'config': str(config_path.relative_to(root))}
            continue
        results = pl.read_parquet(source/'results.parquet')
        verify_run(results, json.loads((source/'run_metadata.json').read_text()), config, root)
        table, counts = score_categories(results, spec, list(config['options']))
        tables.append(table)
        coverage.append(counts)
        manifest[name] = {'status': 'available' if results['probability_valid'].all() else 'partial',
                          'run': source.name, 'config': str(config_path.relative_to(root)),
                          'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
                          'results_sha256': hashlib.sha256((source/'results.parquet').read_bytes()).hexdigest(),
                          'question': config['prompt_styles']['role_play']['question'],
                          'options': config['options']}
    if tables:
        pl.concat(tables).sort('evaluation', 'model_key', 'state', 'option').write_parquet(out/'matched_state_categories.parquet')
        pl.concat(coverage).sort('evaluation', 'model_key', 'state').write_parquet(out/'matched_coverage.parquet')
    (out/'matched_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Save compact usage before ignored raw logs are unavailable in CI/clones.
    # Never invent output tokens for older runs whose usage was not retained.
    from site_data import request_usage
    usage = {}
    for name, spec in manifest.items():
        if spec['status'] == 'pending':
            continue
        folder = root/'data/llm_responses'/spec['run']
        frame = pl.read_parquet(folder/'results.parquet')
        log = folder/'responses.jsonl'
        if (not log.exists() and previous_manifest.get(name, {}).get('results_sha256') == spec['results_sha256']
                and name in previous_usage):
            usage[name] = previous_usage[name]
            continue
        records = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if line.strip()] if log.exists() else []
        usage[name] = {key: request_usage([r for r in records if r['model_key'] == key],
                                         frame.filter(pl.col('model_key') == key)) for key in MODELS}
    (out/'matched_usage.json').write_text(json.dumps(usage, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true', help='Make paid model requests for missing matched runs.')
    parser.add_argument('--evaluations', nargs='+', choices=list(SPECS))
    args = parser.parse_args()
    collect_and_score(collect=args.collect, evaluations=args.evaluations)
