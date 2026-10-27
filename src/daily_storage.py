"""Keep observations on daily-data without changing main or website sources.

Workflow: fetch the storage branch if present -> restore only approved data files
into a checkout of the code -> collect observations -> commit those data files
in a separate worktree. The first save creates an orphan (data-only) branch and
seeds it with the historical observations already committed on main.

Usage: python src/daily_storage.py restore | save
Requires an authenticated origin with push access for save. No force pushes.
Raw responses.jsonl logs, credentials, code, writing and plots are never stored.
"""

from argparse import ArgumentParser
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'daily-data'
RUN_FILES = {'results.parquet', 'summary.parquet', 'run_metadata.json',
             'usage_summary.json', 'resume.json'}


def git(root, *args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check, capture_output=True)


def allowed(path):
    """Only observations, compact retry checkpoints and collection manifests."""
    parts = Path(path).as_posix().split('/')
    if '..' in parts or parts[0] != 'data':
        return False
    if len(parts) == 3 and parts[1] in ('polling_forecast', 'daily_runs'):
        return parts[2].endswith('.json')
    return (len(parts) in (4, 6) and parts[1] == 'llm_responses'
            and parts[-1] in RUN_FILES
            and (len(parts) == 4 or parts[3] == 'models'))


def fetch_storage(root):
    found = git(root, 'ls-remote', '--exit-code', 'origin', f'refs/heads/{BRANCH}', check=False)
    if found.returncode == 2:
        return None
    found.check_returncode()  # Network/auth errors are not a missing branch.
    git(root, 'fetch', '--no-tags', '--depth=1', 'origin', f'refs/heads/{BRANCH}')
    return git(root, 'rev-parse', 'FETCH_HEAD').stdout.decode().strip()


def restore(root=ROOT):
    # Preserve the already published historical costs on the first CI run;
    # raw attempt logs are intentionally absent from the public repository.
    manifest = root / 'docs/data/history.json'
    if manifest.exists():
        history = json.loads(manifest.read_text(encoding='utf-8'))
        usage = {}
        for snapshot in history['snapshots'].values():
            for key, entry in snapshot['models'].items():
                if 'cost' in entry:
                    usage.setdefault(entry['run'], {})[key] = entry['cost']
        for run, values in usage.items():
            path = root / 'data/llm_responses' / run / 'usage_summary.json'
            if path.parent.is_dir() and not path.exists():
                path.write_text(json.dumps(values, indent=2), encoding='utf-8')
    ref = fetch_storage(root)
    if ref is None:
        print('No daily-data branch yet; using observations already in the code checkout.')
        return
    archive = git(root, 'archive', ref).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        for member in files:
            if member.isfile() and allowed(member.name):
                target = root / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(files.extractfile(member).read())
    print(f'Restored observations from daily-data ({ref[:7]}).')


def save(root=ROOT):
    ref = fetch_storage(root)
    # The worktree lives in an ignored directory, separate from checked-out code.
    store = root / '.automation/storage'
    store.parent.mkdir(parents=True, exist_ok=True)
    git(root, 'worktree', 'add', '--detach', str(store), ref or 'HEAD')
    try:
        if ref is None:
            git(store, 'switch', '--orphan', BRANCH)
        for path in (root / 'data').rglob('*'):
            relative = path.relative_to(root)
            if path.is_file() and allowed(relative):
                target = store / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        (store / 'README.md').write_text(
            '# Daily observations\n\nMaintained automatically. Code, tests, writing and '
            'Actions workflows live on main. Do not merge this branch into main.\n', encoding='utf-8')
        git(store, 'add', 'data', 'README.md')
        changed = git(store, 'diff', '--cached', '--quiet', check=False)
        if changed.returncode == 0:
            return
        if changed.returncode != 1:
            changed.check_returncode()
        git(store, '-c', 'user.name=github-actions[bot]', '-c',
            'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit', '-m', 'Archive daily observations')
        commit = git(store, 'rev-parse', 'HEAD').stdout.decode().strip()
        # checkout@v6 scopes credentials to its source checkout. Push through
        # that checkout rather than depending on credentials inside a worktree.
        git(root, 'push', 'origin', f'{commit}:refs/heads/{BRANCH}')
        print('Archived observations on daily-data; code checkout is unchanged.')
    finally:
        git(root, 'worktree', 'remove', '--force', str(store))


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['restore', 'save'])
    args = parser.parse_args()
    (restore if args.command == 'restore' else save)()
