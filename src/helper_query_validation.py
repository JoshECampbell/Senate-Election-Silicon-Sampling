"""Check response validity and manage the post-query retry workflow.

Usage: imported by src/query_llms.py; no standalone command.

Workflow (called automatically by query_llms.py):
1. After the initial query batch, select the latest saved attempt for each
   requested respondent/configuration. Reject cached requests whose actual
   payload or sampled row positions differ from the current inputs.
2. Accept a response only if its status is "ok" and every expected probability
   is numeric, finite, between 0 and 1 inclusive, and the total differs from 1
   by at most 1e-6. Small floating-point differences are accepted unchanged.
3. Collect unresolved requests into a retry batch. Send the SAME persona,
   prompt, model, and options; do not change the question to obtain an answer.
4. Save each retry result and its per-request retry count to the append-only
   log. Recheck unresolved requests in subsequent rounds, up to three additional
   attempts after the initial attempt. Saved retry counts carry across restarts.
5. Return the latest records and retry statistics to the runner. The runner
   expands respondents back into sampled rows, averages valid responses only,
   and writes state-level exclusion counts/percentages into its metadata.

Terminology:
* A job is one unique respondent in one experimental configuration. One job can
  represent several sampled persona rows because sampling uses replacement.
* A record is one completed attempt at a job. Older attempts remain in JSONL;
  only the latest attempt is used when evaluating the current run.
* A retry round contains only still-unresolved jobs with retry budget remaining.
  A job that becomes valid is never sent again by later rounds.

This module does not send HTTP requests or write Parquet files itself. The runner
supplies query/save callbacks, which also allow tests to exercise retries without
network access. HTTP transport retries inside the query callback are separate
from this module's three additional response-validation attempts.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import math
from numbers import Real


# Absolute error in the SUM, not a tolerance allowing negative or >1 values.
PROBABILITY_TOLERANCE = 1e-6
# Three additional logical attempts: at most four including the initial query.
MAX_VALIDATION_RETRIES = 3


def probability_error(record, columns):
    """Return an explanatory error string, or None when the whole vector is valid.

    `columns` lists the parsed probability fields, e.g. p_democrat. The runner's
    parser checks option names/response shape before this numerical check.
    Status is checked first: an error or refusal cannot become a valid vote
    response merely because probability fields happen to be present.
    """
    if record.get("status") != "ok":
        return record.get("error") or f"Response status: {record.get('status', 'missing')}"
    values = [record.get(column) for column in columns]
    # Missing fields become None. Explicitly reject booleans because Python treats
    # True/False as numbers; NaN and infinity must also never enter an average.
    if not values or any(isinstance(value, bool) or not isinstance(value, Real)
                         or not math.isfinite(value) for value in values):
        return "Every option must have a finite numeric probability."
    if any(value < 0 or value > 1 for value in values):
        return "Probabilities must be between 0 and 1 inclusive."
    # fsum reduces addition-order rounding error. Do not demand exact equality,
    # rescale the vector, or judge whether a political preference looks plausible.
    if abs(math.fsum(values) - 1) > PROBABILITY_TOLERANCE:
        return "Probabilities must sum to 1 within an absolute tolerance of 1e-6."
    return None


def payload_hash(payload):
    """Identify an exact request without putting its prompt in a public checkpoint."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def current_records(jobs, records):
    """Match this invocation's jobs to their latest compatible saved attempts.

    JSONL is append-only, so assigning by key in file order selects the last
    attempt. Records for other selections are ignored. A matching key alone is
    insufficient: changing a prompt or sampled multiplicity under the same run
    name could otherwise silently reuse an answer from a different experiment.
    """
    latest = {record["key"]: record for record in records}
    selected = {}
    for job in jobs:
        record = latest.get(job["key"])
        if record is None:
            continue
        # Compare actual inputs, including all row positions served by the answer.
        # The fallback supports records written before persona_rows was a list.
        same_payload = (record['payload'] == job['payload'] if 'payload' in record else
                        record.get('payload_sha256') == payload_hash(job['payload']))
        if (not same_payload
                or record.get("persona_rows", [record.get("persona_row")]) != job["persona_rows"]):
            raise ValueError("Saved requests differ from the current inputs. Use a new --run-name.")
        selected[job["key"]] = record
    return selected


def retry_invalid_queries(jobs, latest, columns, query, save_record, *, workers=8,
                          max_retries=MAX_VALIDATION_RETRIES):
    """Retry unresolved jobs, returning (updated_latest_records, retry_statistics).

    `latest` maps job keys to recorded attempts; it is copied before updating.
    `query(job)` returns an attempt record (the runner uses run_job, which records
    API exceptions as error statuses). `save_record(record)` appends and flushes
    that attempt to JSONL. File writes happen here in the collecting thread,
    rather than concurrently inside HTTP workers.

    `validation_retry` is a PER-JOB count saved with each retry. `retry_rounds`
    and `retry_requests` describe work during THIS invocation. For example, a
    resumed job already at retry 2 can receive only retry 3, not three new tries.
    max_retries=0 disables the stage after the runner's initial-error early stop.
    """
    latest = dict(latest)
    retry_requests = 0
    retry_rounds = 0
    for _ in range(max_retries):
        # Rebuild the batch after each round: recovered jobs drop out, and jobs
        # whose recorded retry count reached the limit stay excluded on restart.
        pending = [job for job in jobs if probability_error(latest.get(job["key"], {}), columns)
                   and latest.get(job["key"], {}).get("validation_retry", 0) < max_retries]
        if not pending:
            break
        retry_rounds += 1
        print(f"Validation retry round {retry_rounds}: {len(pending)} unique requests")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Pass original jobs unchanged. The future-to-job map reconnects
            # responses to the right respondent despite out-of-order completion.
            futures = {pool.submit(query, job): job for job in pending}
            for future in as_completed(futures):
                job = futures[future]
                record = future.result()
                record["validation_retry"] = latest.get(job["key"], {}).get("validation_retry", 0) + 1
                reason = probability_error(record, columns)
                # Defend against callbacks (or older code) marking malformed
                # probabilities "ok". Preserve explicit error/refusal statuses.
                if reason and record.get("status") == "ok":
                    record.update(status="invalid", error=reason)
                # Persist before proceeding to another round. Both successful
                # replacements and unsuccessful retries remain auditable.
                save_record(record)
                latest[job["key"]] = record
                retry_requests += 1
    return latest, {"retry_rounds": retry_rounds, "retry_requests": retry_requests,
                    "max_validation_retries": MAX_VALIDATION_RETRIES,
                    "probability_tolerance": PROBABILITY_TOLERANCE}


def clean_metadata(metadata):
    """Remove legacy config copies/Git fields from metadata, updating it in place.

    Keep CLI arguments (including the config FILE PATH), timestamps, and counts.
    Exact request payloads already live in the response log; the full YAML config
    is not duplicated into metadata. This also cleans older invocations on resume.
    """
    metadata.pop("config", None)
    metadata.pop("git_commit", None)
    for invocation in metadata.get("invocations", []):
        invocation.pop("git_commit", None)
    return metadata
