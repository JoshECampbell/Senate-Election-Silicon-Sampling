"""Tests of the website's model-validation figures and section.

- The back-cast scatter draws one dot per state and the correction curve.
- The error chart draws a raw and a corrected mark per state and keeps errors
  beyond +/-40 points inside the plot.
- The calibration chart draws one marker per saved point and skips models
  without points.
- The section builder reports missing validation outputs instead of failing,
  and with the saved outputs writes every figure and one table row per model.
- The back-cast cost table is empty without the run and totals the per-model
  costs with it.

Usage: uv run python -m unittest discover -s test -p 'test_validation_figures.py' -v
"""

from pathlib import Path
import re
import sys
import tempfile
import unittest

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from prepare_website import FigureCache, backcast_costs, model_validation_section
from site_figures import backcast_figure, calibration_figure, error_figure

MODELS = {"jev": {"label": "Jev", "shape": "circle", "dash": ""},
          "mercury": {"label": "Mercury", "shape": "triangle", "dash": "7 4"}}


def state_rows(n=5):
    return [{"state": f"State {i}", "predicted_two_party": 0.1 + 0.15 * i, "actual_two_party": 0.35 + 0.05 * i,
             "corrected_two_party": 0.36 + 0.05 * i, "error": 0.1 * i - 0.2, "held_out_error": 0.01 * i}
            for i in range(n)]


class FigureTests(unittest.TestCase):
    def test_backcast_has_a_dot_per_state_and_a_curve(self):
        svg = backcast_figure("Jev", state_rows(), -0.2, 0.24)
        self.assertEqual(svg.count("<circle"), 5)
        self.assertEqual(svg.count("<polyline"), 1)
        self.assertIn("slope 0.24", svg)

    def test_errors_have_two_marks_per_state_and_stay_in_bounds(self):
        rows = state_rows(3)
        rows[0]["error"] = 0.9  # 90 points: must be drawn at the +40 edge
        svg = error_figure("Jev", rows)
        self.assertEqual(svg.count("<circle"), 6)
        xs = [float(x) for x in re.findall(r'<circle cx="([\d.]+)"', svg)]
        self.assertTrue(all(112 <= x <= 330 for x in xs))

    def test_calibration_marks_each_point_and_skips_empty_models(self):
        rows = [{"model_key": "jev", "predicted": p, "actual": p + 0.1, "n": 10} for p in (0.1, 0.5, 0.9)]
        svg = calibration_figure(rows, MODELS)
        self.assertEqual(svg.count('class="calibration-dot"'), 3)
        self.assertEqual(svg.count("<polyline"), 1)


class SectionTests(unittest.TestCase):
    def test_missing_outputs_give_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = model_validation_section(Path(tmp), Path(tmp) / "docs", FigureCache(Path(tmp)), MODELS)
        self.assertIn("Run src/validate_models.py", html)

    @unittest.skipUnless((ROOT / "data/model_validation/backcast_summary.parquet").exists(),
                         "Run src/validate_models.py first.")
    def test_saved_outputs_give_every_figure_and_row(self):
        models = {key: {**MODELS["jev"], "label": key} for key in
                  pl.read_parquet(ROOT / "data/model_validation/backcast_summary.parquet")["model_key"]}
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            html = model_validation_section(ROOT, site, FigureCache(site), models)
            figures = sorted(p.name for p in (site / "figures/validation").iterdir())
        self.assertEqual(len(figures), 2 * len(models) + 1)
        self.assertEqual(html.count("<tr><th scope=\"row\">"), len(models))

    def test_backcast_costs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(backcast_costs(Path(tmp), MODELS), "")
            folder = Path(tmp) / "data/llm_responses/backcast-2024"
            folder.mkdir(parents=True)
            pl.DataFrame({"model_key": ["jev", "jev", "jev", "mercury"], "state": ["A", "A", "B", "A"],
                          "caseid": [1.0, 1.0, 2.0, 1.0], "cost_usd": [0.01, 0.01, 0.02, 0.0],
                          "input_tokens": [100, 100, 120, 90]}).write_parquet(folder / "results.parquet")
            html = backcast_costs(Path(tmp), MODELS)
        # The repeated (A, 1) draw for jev is one request, not two.
        self.assertIn("<td>3</td><td>310</td><td>$0.03000</td>", html)


if __name__ == "__main__":
    unittest.main()
