"""Tests run:
- Check date-based folder names and the requirement for 35 complete 100-draw states.
- Preserve retry checkpoints and cumulative costs across a rerun without storing prompts.
- Merge a successful model alongside failed models and retain earlier polling.
- Skip daily publication after total model failure while allowing website-only builds.
- Create, update and restore a data-only Git branch without changing the source branch.
- Reject source files, raw logs and escaping paths from the storage branch.

Usage: uv run python -m unittest discover -s test -p 'test_daily_automation.py' -v
All subprocess/API examples are mocked or use temporary local Git repositories.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from daily_automation import collect_model, complete_model, gate, merge, run_name, write_json
from daily_storage import allowed, git, restore, save
from helper_query_validation import current_records


def complete_metadata():
    return {'validation': {'states': [{'state': f'State {i}', 'n': 100, 'n_valid': 100,
                                       'complete': True} for i in range(35)]}}


class DailyAutomationTests(unittest.TestCase):
    def test_dates_and_complete_model_rule(self):
        self.assertEqual(run_name('2026-10-28'), 'oct-28-no-luna')
        self.assertEqual(run_name('2026-11-03'), 'nov-03-no-luna')
        metadata = complete_metadata()
        self.assertTrue(complete_model(metadata))
        metadata['validation']['states'][0]['n_valid'] = 99
        self.assertFalse(complete_model(metadata))
        self.assertFalse(complete_model({'validation': {'states': []}}))

    def test_resume_preserves_usage_and_omits_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            settings = yaml.safe_load((ROOT / 'config/daily_run.yaml').read_text())
            (root / 'config/daily_run.yaml').write_text(yaml.safe_dump(settings))
            folder = root / 'data/llm_responses/oct-28-no-luna/models/jev'
            job = {'key': 'one', 'payload': {'context': 'artificial persona'}, 'persona_rows': [0]}

            def fake_query(args, cwd, check):
                # First run: two bad attempts followed by recovery; second run
                # finds its checkpoint and issues no new provider requests.
                if not (folder / 'resume.json').exists():
                    with open(folder / 'responses.jsonl', 'a') as log:
                        for retry in range(3):
                            log.write(json.dumps({**job, 'validation_retry': retry,
                                      'response': {'usage': {'input_tokens': 10, 'output_tokens': 2,
                                                              'cost': .01}},
                                      'persona_text': 'artificial persona'}) + '\n')
                write_json(folder / 'run_metadata.json', complete_metadata())
                return SimpleNamespace(returncode=0)

            with patch('daily_automation.subprocess.run', side_effect=fake_query):
                collect_model('2026-10-28', 'jev', root)
                collect_model('2026-10-28', 'jev', root)
            usage = json.loads((folder / 'usage_summary.json').read_text())
            self.assertEqual(usage['attempts'], 3)
            self.assertEqual(usage['input_tokens'], 30)
            self.assertEqual(usage['output_tokens'], 6)
            self.assertAlmostEqual(usage['known_cost'], .03)
            checkpoint = json.loads((folder / 'resume.json').read_text())
            self.assertNotIn('payload', checkpoint[0])
            self.assertNotIn('persona_text', checkpoint[0])
            self.assertNotIn('response', checkpoint[0])
            self.assertIn('one', current_records([job], checkpoint))
            with self.assertRaises(ValueError):
                current_records([{**job, 'payload': {'context': 'changed'}}], checkpoint)

    def test_partial_success_and_polling_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/daily_run.yaml').write_text('models: [jev, mercury, decider]\n')
            earlier = root / 'data/polling_forecast/2026-10-27.json'
            write_json(earlier, {'forecast': {'asOf': '2026-10-27'}})
            for model in ('jev', 'mercury'):
                incoming = root / '.automation/incoming' / f'llm-{model}'
                write_json(incoming / 'collection_status.json', {'complete': model == 'jev'})
                pl.DataFrame({'model_key': [model]}).write_parquet(incoming / 'results.parquet')
                pl.DataFrame({'model_key': [model]}).write_parquet(incoming / 'summary.parquet')
            write_json(root / '.automation/incoming/polling/status.json', {'success': False})
            merge('2026-10-28', '123', root)
            self.assertTrue(earlier.exists())
            self.assertFalse((earlier.parent / '2026-10-28.json').exists())
            meta = json.loads((root / 'data/llm_responses/oct-28-no-luna/run_metadata.json').read_text())
            self.assertEqual(meta['published_models'], ['jev'])
            history = {'snapshots': {'2026-10-28': {'models': {'jev': {'complete': True}}}}}
            with patch('daily_automation.load_history', return_value=history):
                self.assertTrue(gate('123', root))
            write_json(root / 'data/daily_runs/124.json', {'successful_models': []})
            with patch('daily_automation.load_history', side_effect=AssertionError('No build needed')):
                self.assertFalse(gate('124', root))
                self.assertTrue(gate(None, root))

    def test_storage_allowlist(self):
        self.assertTrue(allowed('data/llm_responses/oct-28-no-luna/models/jev/resume.json'))
        for path in ('src/query_llms.py', 'docs/index.qmd', '../data/polling_forecast/x.json',
                     'data/llm_responses/oct-28-no-luna/responses.jsonl', '.env'):
            self.assertFalse(allowed(path), path)

    def test_data_branch_creation_update_and_restore_leave_main_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'code'
            root.mkdir()
            remote = Path(directory) / 'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            git(root, 'init', '-b', 'main')
            git(root, 'remote', 'add', 'origin', str(remote))
            (root / 'src').mkdir()
            (root / 'src/writing.txt').write_text('Website source must stay on main.')
            path = root / 'data/llm_responses/oct-28-no-luna/run_metadata.json'
            write_json(path, {'version': 1})
            git(root, 'add', '.')
            git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'Code')
            original = git(root, 'rev-parse', 'HEAD').stdout
            (path.parent / 'responses.jsonl').write_text('never archive this raw log')
            save(root)
            ref = git(root, 'ls-remote', 'origin', 'refs/heads/daily-data').stdout.decode().split()[0]
            names = git(root, 'ls-tree', '-r', '--name-only', ref).stdout.decode()
            self.assertIn('run_metadata.json', names)
            self.assertNotIn('src/', names)
            self.assertNotIn('responses.jsonl', names)
            self.assertEqual(git(root, 'rev-parse', 'HEAD').stdout, original)
            write_json(path, {'version': 2})
            save(root)
            path.unlink()
            restore(root)
            self.assertEqual(json.loads(path.read_text())['version'], 2)
            self.assertEqual(git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip(), b'main')


if __name__ == '__main__':
    unittest.main()
