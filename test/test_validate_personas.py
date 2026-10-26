"""Check the comparison with small inputs whose answers are known."""

import tempfile
import unittest
from pathlib import Path

import polars as pl

from validate_personas import category_spec, check_personas, compare_feature


class PersonaValidationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "age_reference_year": 2025, "age_bin_edges": [18, 30, 45, 65, 121],
            "no_response_labels": ["Skipped", "Not Asked"],
        }
        self.labels = {"race": {"codes": {1: "A", 2: "B", 98: "Skipped"}},
                       "sexuality": {"codes": {1: "Straight", 6: "Prefer not to say", 8: "Skipped"},
                                     "missing": [6, 8]}}

    def test_reference_weights_and_repeated_persona_draws(self):
        reference = pl.DataFrame({"race": [1, 2], "commonweight": [1., 3.]})
        # The three B draws must count three times, without another survey weight.
        personas = pl.DataFrame({"race": [1, 2, 2, 2], "commonweight": [1., 3., 3., 3.]})
        result = compare_feature(reference, personas, "race", self.settings, self.labels)
        self.assertEqual([r["reference_share"] for r in result], [.25, .75, 0.])
        self.assertEqual([r["persona_share"] for r in result], [.25, .75, 0.])
        self.assertTrue(all(r["difference_pp"] == 0 for r in result))

    def test_missing_unknown_and_absent_categories_keep_full_denominator(self):
        reference = pl.DataFrame({"race": [1, 98, None, 42], "commonweight": [1., 1., 1., 1.]})
        personas = pl.DataFrame({"race": [2, 2]})
        result = {r["category"]: r for r in compare_feature(reference, personas, "race", self.settings, self.labels)}
        self.assertEqual(result["No response"]["reference_share"], .5)
        self.assertEqual(result["Unknown code: 42"]["reference_share"], .25)
        self.assertEqual(result["B"]["persona_share"], 1.)
        self.assertEqual(result["B"]["reference_share"], 0.)
        self.assertAlmostEqual(sum(r["reference_share"] for r in result.values()), 1.)
        self.assertAlmostEqual(sum(r["persona_share"] for r in result.values()), 1.)

    def test_refusal_is_visible_even_if_omitted_from_prompts(self):
        _, label = category_spec("sexuality", self.settings, self.labels)
        self.assertEqual(label(6), "Prefer not to say")
        self.assertEqual(label(8), "No response")

    def test_age_boundaries_and_invalid_values(self):
        _, label = category_spec("age", self.settings, self.labels)
        for age, expected in [(18, "18-29"), (29, "18-29"), (30, "30-44"),
                              (44, "30-44"), (45, "45-64"), (64, "45-64"),
                              (65, "65-120"), (120, "65-120")]:
            self.assertEqual(label(2025 - age), expected)
        for value in [2026, 2008, 1904, 1990.5, float("inf")]:
            self.assertEqual(label(value), "Outside age range / invalid birth year")
        self.assertEqual(label(None), "No response")

    def test_invalid_weights_stop_comparison(self):
        for weights in ([0., 0.], [-1., 2.], [float("nan"), 1.], [float("inf"), 1.], [None, 1.]):
            reference = pl.DataFrame({"race": [1, 2], "commonweight": weights})
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                compare_feature(reference, pl.DataFrame({"race": [1]}), "race", self.settings, self.labels)

    def test_source_checks_accept_duplicates_and_reject_mismatch(self):
        reference = pl.DataFrame({"caseid": [1], "inputstate": [1], "race": [1]})
        check_personas(reference, pl.concat([reference, reference]), ["race"], 1)
        for changed in [reference.with_columns(pl.lit(2).alias("inputstate")),
                        reference.with_columns(pl.lit(2).alias("caseid")),
                        reference.with_columns(pl.lit(2).alias("race")), reference.head(0)]:
            with self.assertRaises(ValueError):
                check_personas(reference, changed, ["race"], 1)

    def test_cli_writes_tables_plot_and_metadata(self):
        import subprocess
        import sys
        import yaml

        # Use temporary files. Do not alter the real persona data.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            personas = root / "personas"
            personas.mkdir()
            reference = pl.DataFrame({"caseid": [1, 2, 3], "inputstate": [1, 1, 2],
                                      "race": [1, 2, 1], "commonweight": [1., 3., 9.]})
            reference.write_parquet(root / "reference.parquet")
            reference[[0, 1, 1, 1]].write_parquet(personas / "Alabama")
            (personas / "persona_config.yaml").write_text("seed: 42\n", encoding="utf-8")
            subprocess.run([sys.executable, "test/validate_personas.py", "--run-name", "fixture",
                            "--personas", str(personas), "--data-path", str(root / "reference.parquet"),
                            "--output-dir", str(root / "output"), "--features", "race", "--states", "Alabama"],
                           check=True, capture_output=True, text=True)
            output = root / "output" / "fixture"
            result = pl.read_parquet(output / "fixture_distributions.parquet")
            self.assertEqual(result["reference_total_count"].unique().to_list(), [2])
            self.assertAlmostEqual(result["difference_pp"].abs().sum(), 0.)
            summary = pl.read_parquet(output / "fixture_summary.parquet")
            self.assertEqual(summary["total_variation_distance"][0], 0.)
            metadata = yaml.safe_load((output / "fixture_validation.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                metadata,
                {
                    "reference": str(root / "reference.parquet"),
                    "personas": {
                        "directory": str(personas),
                        "total_draws": 4,
                        "states": {
                            "Alabama": {
                                "persona_file": str(personas / "Alabama"),
                                "persona_draws": 4,
                                "reference_population": 2,
                            }
                        },
                    },
                },
            )
            self.assertTrue((output / "plots" / "Alabama.png").is_file())


if __name__ == "__main__":
    unittest.main()
