"""Tests run:
- Accept valid probability vectors and reject incomplete, malformed, nonfinite or out-of-range responses.
- Check exact response options and preserve raw provider bodies when parsing fails.
- Verify identical retry requests, the three-retry cap, saved budgets and changed-input rejection.
- Check repeated-draw averages, exclusion counts and metadata cleanup.
- Run mocked end-to-end queries and resumes without network calls or duplicate requests.

Usage: uv run python -m unittest discover -s test -p 'test_query_validation.py' -v
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from collections import Counter
from contextlib import redirect_stdout
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import polars as pl
# Make src modules importable when unittest discovers tests from the test folder.
import query_llms as query
from helper_query_validation import (clean_metadata, current_records,
                                     probability_error, retry_invalid_queries)


OPTIONS = ["Democrat", "Republican", "Third party", "Would not vote"]
# Provider labels and saved-column names differ; fixtures exercise that mapping.
COLS = [query.slug(option) for option in OPTIONS]


def response(values):
    """Construct the minimal OpenRouter response body consumed by the real parser."""
    return {"model": "test-model", "answers": {"vote": {"type": "choice",
            "probabilities": dict(zip(OPTIONS, values))}}}


def record(job, values, status="ok"):
    """Construct an already-parsed attempt for tests that isolate later stages."""
    return {**job, "status": status, **dict(zip(COLS, values))}


class QueryValidationTests(unittest.TestCase):
    """Check numerical rules first, then retries, aggregation, and the whole runner."""

    def test_endpoints_and_float_noise_are_valid(self):
        """Exactly 0/1 are valid; a total of 1.0000005 is within the 1e-6 tolerance."""
        for values in ([1., 0., 0., 0.], [0., 1., 0., 0.],
                       [.1, .2, .3, .4], [.5, .5000005, 0., 0.]):
            with self.subTest(values=values):
                self.assertIsNone(probability_error(record({}, values), COLS))

    def test_incomplete_nonfinite_nonnumeric_bounds_and_sum_are_rejected(self):
        """An invalid component invalidates the whole four-option vector."""
        # Cover each rejection independently. A boolean must fail even though
        # Python treats True as 1; a numeric-looking string is not a JSON number.
        for values in ([None, .5, .25, .25], [True, 0., 0., 0.], ["0.5", .5, 0., 0.],
                       [float("nan"), .5, .25, .25], [float("inf"), 0., 0., 0.],
                       [-.1, .6, .25, .25], [1.1, 0., 0., 0.], [.5, .50001, 0., 0.]):
            with self.subTest(values=values):
                self.assertIsNotNone(probability_error(record({}, values), COLS))
        # A refusal is unresolved even if a response includes plausible numbers.
        self.assertIsNotNone(probability_error(record({}, [.25]*4, "refused"), COLS))

    def test_response_options_must_be_complete_unique_and_exact(self):
        """Reject missing/extra/duplicate labels and vectors of the wrong length."""
        for probabilities in ({"Democrat": 1.}, {**dict(zip(OPTIONS, [.25]*4)), "Extra": 0.},
                              [{"value": "Democrat", "probability": .5}]*2, [.5, .5]):
            with self.subTest(probabilities=probabilities), self.assertRaises(ValueError):
                query._probabilities_to_dict(probabilities, OPTIONS)
        # A positional list with exactly four entries remains a supported format.
        self.assertEqual(query._probabilities_to_dict([.25]*4, OPTIONS), dict(zip(OPTIONS, [.25]*4)))

    def test_run_job_classifies_bad_response_without_losing_raw_body(self):
        """The attempt is marked invalid, while its original body is retained."""
        job = {"model_key": "test", "payload": {}}
        cfg = {"models": {"test": {"provider": "openrouter_decisions"}},
               "options": dict.fromkeys(OPTIONS)}
        body = response([1.2, -.2, 0., 0.])
        # Replace only HTTP execution: production parsing and validation still run.
        with patch.object(query, "call_api", return_value=body):
            result = query.run_job(job, cfg)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["response"], body)
        # Refusals must keep their own status rather than become non-voting answers.
        refusal = {"answers": {"vote": {"type": "refusal"}}}
        with patch.object(query, "call_api", return_value=refusal):
            self.assertEqual(query.run_job(job, cfg)["status"], "refused")

    def test_batched_recovery_retry_cap_and_resume_budget(self):
        """Recovery stops retries for that job; persistent failure gets only three."""
        # Two jobs represent four draws. "recover" serves THREE rows but should
        # receive only one request per retry round, not three copies of the request.
        jobs = [{"key": key, "persona_rows": rows, "payload": {"person": key}}
                for key, rows in [("recover", [0, 1, 2]), ("fail", [3])]]
        latest = {job["key"]: record(job, [.1]*4) for job in jobs}
        attempts, saved = Counter(), []
        def send(job):
            # .1 across four options sums to .4 (invalid). The recovering job
            # switches to .25 each (valid) only on its second additional attempt.
            attempts[job["key"]] += 1
            values = [.25]*4 if job["key"] == "recover" and attempts["recover"] == 2 else [.1]*4
            return record(job, values)
        with redirect_stdout(io.StringIO()):
            latest, info = retry_invalid_queries(jobs, latest, COLS, send, saved.append, workers=2)
        # Expected work: 2 retries for recovery + 3 for permanent failure = 5.
        self.assertEqual(attempts, {"recover": 2, "fail": 3})
        self.assertEqual(info["retry_requests"], 5)
        self.assertIsNone(probability_error(latest["recover"], COLS))
        self.assertEqual(latest["recover"]["persona_rows"], [0, 1, 2])
        self.assertEqual(latest["fail"]["validation_retry"], 3)
        self.assertEqual(len(saved), 5)
        # Model a restart with saved latest records. Neither recovered nor exhausted
        # jobs should be queried; fail loudly if any callback is invoked.
        resumed_send = Mock(side_effect=AssertionError("Retry cap must survive restart"))
        with redirect_stdout(io.StringIO()):
            _, resumed = retry_invalid_queries(jobs, latest, COLS, resumed_send, saved.append)
        resumed_send.assert_not_called()
        self.assertEqual(resumed["retry_requests"], 0)

    def test_errors_and_refusals_are_retried_with_unchanged_requests(self):
        """Both unresolved statuses can recover without rewriting the prompt."""
        for status in ("error", "refused"):
            job = {"key": status, "payload": {"original": "question"}, "persona_rows": [0]}
            sent = Mock(return_value=record(job, [.25]*4))
            with redirect_stdout(io.StringIO()):
                latest, _ = retry_invalid_queries([job], {status: record(job, [None]*4, status)},
                                                  COLS, sent, lambda rec: None)
            sent.assert_called_once_with(job)
            self.assertIsNone(probability_error(latest[status], COLS))

    def test_changed_cached_inputs_require_a_new_run(self):
        """A matching label/key cannot justify reusing a different experiment."""
        job = {"key": "same", "payload": {"question": "original"}, "persona_rows": [0, 1]}
        # Test a changed question and a changed sampled multiplicity separately.
        for changed in ({**job, "payload": {"question": "changed"}}, {**job, "persona_rows": [0]}):
            with self.assertRaisesRegex(ValueError, "new --run-name"):
                current_records([job], [changed])

    def test_summary_preserves_multiplicity_and_excludes_entire_bad_vectors(self):
        """Check weighted-by-draw means, exclusions, and an entirely invalid state."""
        def job(key, state, rows):
            return {"key": key, "state": state, "persona_rows": rows, "caseid": key,
                    "model_key": "test", "persona_level": 9, "prompt_style": "role_play",
                    "persona_format": "sentence", "news": "none", "payload": {"person": key}}
        # Alabama: a occurs 3 times, b once, and c twice (6 expected draws).
        # a/b are valid; c is incomplete and must lose ALL four probabilities,
        # including its present Democrat value. Alaska has 2 failed draws only.
        jobs = [job("a", "Alabama", [0, 1, 2]), job("b", "Alabama", [3]),
                job("c", "Alabama", [4, 5]), job("d", "Alaska", [0, 1])]
        records = [record(jobs[0], [.2, .6, .1, .1]), record(jobs[1], [.8, .1, .05, .05]),
                   record(jobs[2], [.9, None, None, None]), record(jobs[3], [None]*4, "error")]
        with tempfile.TemporaryDirectory() as directory:
            # Exercise real JSONL reading and Parquet writing, confined to temp files.
            root = Path(directory)
            (root / "responses.jsonl").write_text("".join(json.dumps(r)+"\n" for r in records))
            with redirect_stdout(io.StringIO()):
                counts = query.write_results(root, {"options": dict.fromkeys(OPTIONS)}, jobs)
            result = pl.read_parquet(root / "results.parquet")
            summary = pl.read_parquet(root / "summary.parquet")
        # Result rows retain every expected draw, including excluded ones.
        self.assertEqual(result.height, 8)
        a = summary.filter(pl.col("state") == "Alabama").row(0, named=True)
        self.assertEqual((a["n"], a["n_valid"], a["n_invalid"], a["n_unique_invalid"]), (6, 4, 2, 1))
        # 2 excluded draws / 6 expected draws = 33.333...%, although only one
        # unique Alabama respondent failed. Valid Democrat mean uses 4 draws.
        self.assertAlmostEqual(a["invalid_percentage"], 100/3)
        self.assertAlmostEqual(a["p_democrat"], .35)  # (3*.2 + .8)/4, not (.2+.8)/2
        self.assertAlmostEqual(sum(a[c] for c in COLS), 1.)
        self.assertFalse(a["complete"])
        # Keep the all-invalid state visible with null means, rather than inventing
        # zero vote probabilities or silently dropping the state from the summary.
        alaska = summary.filter(pl.col("state") == "Alaska").row(0, named=True)
        self.assertEqual((alaska["n_valid"], alaska["n_invalid"], alaska["invalid_percentage"]), (0, 2, 100.))
        self.assertTrue(all(alaska[c] is None for c in COLS))
        self.assertEqual(len(counts), 2)

    def test_metadata_cleanup_keeps_arguments_and_tracking(self):
        """Remove the config COPY/Git field while keeping the config PATH argument."""
        old = {"config": {"large": "copy"}, "invocations": [
            {"git_commit": "old-hash", "args": {"config": "config/query_config.yaml"}, "n_requests": 2}]}
        cleaned = clean_metadata(old)
        self.assertNotIn("config", cleaned)
        self.assertNotIn("git_commit", cleaned["invocations"][0])
        self.assertEqual(cleaned["invocations"][0]["args"]["config"], "config/query_config.yaml")

    def run_main_fixture(self, always_invalid=False):
        """Run the real CLI orchestration twice against an isolated four-draw sample.

        Two source respondents supply four draws: the first appears three times.
        With workers=1, mocked responses are consumed in a predictable order.
        always_invalid chooses between a recoverable run and exhausted retries.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            personas = root / "personas"
            personas.mkdir()
            reference = pl.DataFrame({"caseid": [1, 2], "inputstate": [1, 1], "race": [1, 2],
                                      "gender4": [1, 2], "educ": [2, 5], "religpew": [1, 2],
                                      "marstat": [1, 5], "sexuality": [1, 4], "votereg": [1, 1],
                                      "faminc_new": [5, 10], "commonweight": [1., 3.]})
            # Repeated source rows test the complete deduplicate -> query -> expand
            # path. The YAML verifies that tracking metadata is skipped by the loader.
            reference[[0, 0, 0, 1]].write_parquet(personas / "Alabama.parquet")
            (personas / "persona_config.yaml").write_text("seed: 42\n")
            args = SimpleNamespace(run_name="fixture", personas=str(personas), config="config/query_config.yaml",
                                   models=["mercury"], persona_level=[9], persona_format=["sentence"],
                                   prompt_style=["role_play"], news_file=None, states=None, limit=None,
                                   workers=1, dry_run=False, smoke_test=False)
            output = root / "output"
            if always_invalid:
                # Both unique respondents fail the initial attempt and all retries.
                send = Mock(return_value=response([.1]*4))
            else:
                # Initial respondent A fails, B succeeds, then A's first retry succeeds.
                send = Mock(side_effect=[response([.1]*4), response([.25]*4), response([.25]*4)])
            # Keep production parsing, retrying, logging, metadata, and aggregation;
            # replace the API boundary and input/output locations, not the logic.
            with patch.object(query, "args_parser", return_value=args), patch.object(query, "OUTPUT_ROOT", output), \
                 patch.object(query, "load_dotenv"), patch.object(query, "call_api", send), redirect_stdout(io.StringIO()):
                query.main()
            # Exhaustion: 2 initial + (2 respondents * 3 retries) = 8 logical calls.
            # Recovery: 2 initial + 1 retry = 3. Repeated draws add no API calls.
            self.assertEqual(send.call_count, 8 if always_invalid else 3)
            folder = output / "fixture"
            meta = json.loads((folder / "run_metadata.json").read_text())
            self.assertNotIn("config", meta)
            self.assertNotIn("git_commit", meta["invocations"][0])
            self.assertEqual(meta["validation"]["states"][0]["n_invalid"], 4 if always_invalid else 0)
            self.assertEqual(meta["validation"]["complete"], not always_invalid)
            self.assertEqual(pl.read_parquet(folder / "results.parquet").height, 4)
            # Invoke main again with the same run directory. Its persisted JSONL
            # must prevent both duplicate successful calls and a reset retry budget.
            forbidden = Mock(side_effect=AssertionError("Resume must not requery successful or exhausted requests"))
            with patch.object(query, "args_parser", return_value=args), patch.object(query, "OUTPUT_ROOT", output), \
                 patch.object(query, "load_dotenv"), patch.object(query, "call_api", forbidden), redirect_stdout(io.StringIO()):
                query.main()
            forbidden.assert_not_called()

    def test_full_runner_recovers_and_resumes_without_duplicate_queries(self):
        """One invalid response recovers; four result rows survive; resume sends none."""
        self.run_main_fixture()

    def test_full_runner_exhausts_three_retries_and_preserves_budget_on_resume(self):
        """All draws stay tracked but excluded after exhaustion; resume sends none."""
        self.run_main_fixture(always_invalid=True)


if __name__ == "__main__":
    unittest.main()
