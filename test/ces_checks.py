"""Shared checks called by the real-data and simulated-data test scripts.

- Require the same 17 columns and storage types as the current cleaned export.
- Check unique, positive integer-valued IDs and finite, positive survey weights.
- Check adult birth years for CES 2025 and allowed codebook values, including missing codes.
- Allow genuine null responses while requiring IDs, states, birth years and weights.

Usage: imported by test_ces_data.py and test_simulated_ces_data.py.
"""

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from data_cleaning import CES_SCHEMA

LABELS = yaml.safe_load((ROOT / 'config/ces_codes/ces25_value_labels.yaml').read_text())['variables']


def assert_schema(case, frame):
    """Accept no missing or extra fields and no accidental type conversions."""
    case.assertEqual(frame.columns, list(CES_SCHEMA), 'Expected the 17 cleaned columns in order.')
    case.assertEqual(dict(frame.schema), CES_SCHEMA, 'Cleaned CES storage types changed.')


def assert_ranges(case, frame):
    """Apply the same lightweight value checks to real and artificial rows."""
    case.assertGreater(frame.height, 0, 'The dataset must not be empty.')
    for column in ('caseid', 'inputstate', 'birthyr', 'commonweight'):
        case.assertEqual(frame[column].null_count(), 0, f'{column} must not be null.')
    ids = frame['caseid']
    case.assertEqual(ids.n_unique(), frame.height, 'Respondent IDs must be unique.')
    case.assertTrue(ids.is_finite().all() and (ids > 0).all() and (ids == ids.floor()).all(),
                    'Respondent IDs must be positive finite whole numbers.')
    weights = frame['commonweight']
    case.assertTrue(weights.is_finite().all() and (weights > 0).all(),
                    'Survey weights must be finite and positive; there is no arbitrary upper cap.')
    case.assertTrue(frame['birthyr'].is_between(1905, 2007).all(),
                    'CES 2025 adult ages must be 18–120 (birth years 1905–2007).')
    for column, spec in LABELS.items():
        if 'codes' in spec:
            observed = set(frame[column].drop_nulls().to_list())
            case.assertFalse(observed - set(spec['codes']), f'{column} contains undocumented codes.')
