"""Query decision models for synthetic 2026 Senate vote choices from CES personas.

Each request gives a model one persona (context) and one four-option choice
question. Decision models return a probability for every option, and we store
the full distribution, not just the top pick.

Workflow for a normal run:
1. Read CLI selections and config: persona files, models, characteristic levels,
   list/sentence formats, prompt styles, and optional news conditions.
2. Load the sampled rows, keeping each row's state file and position. Skip YAML
   tracking files; keep repeated respondent draws because they carry sample mass.
3. Group rows by state + CES caseid and build one initial request for each
   respondent/configuration. Remember every sampled row served by that request.
4. Check the saved log for compatible requests. Reuse valid saved responses;
   send initial requests only for jobs with no saved attempt. Append responses
   immediately, including failures, so the run can be resumed.
5. Validate the four probabilities. The helper retries unresolved unique jobs
   with identical requests, up to three additional attempts per job. Logged
   retry counts preserve the remaining budget when restarting.
6. Expand each respondent's final record back to all its sampled row positions.
   Keep unresolved rows for tracking, but set all their probability fields null.
7. Average valid probability vectors within each state/configuration, preserving
   repeated draws. Record expected, valid, and excluded counts and percentages;
   mark incomplete groups explicitly. With no valid rows, averages are null.
8. Save Parquet results/summaries and finish the invocation's metadata. Metadata
   tracks arguments, times, and validation counts without a config copy or Git
   revision; exact requests and attempt history remain in responses.jsonl.

--dry-run stops after request construction and sends nothing. --smoke-test sends
one request per selected model and prints it; it does not run the full batch,
post-batch retry workflow, or normal output-writing steps.

Supported providers (set in config/query_config.yaml):
  - openrouter_decisions: TypeSafe Jev via OpenRouter's Decisions API
  - openai_decisions:     OpenAI's Decisions API (gpt-6-luna)

Outputs go to data/llm_responses/<run-name>/:
  responses.jsonl     every request + raw response, appended as it runs (resumable)
  results.parquet     one tidy row per persona x configuration
  summary.parquet     mean probabilities by state x configuration, with n (persona
                      rows) and n_unique (distinct CES respondents behind them)
  run_metadata.json   arguments, timestamps, validation and exclusion counts

Typical use:
  uv run python src/query_llms.py --run-name pilot --dry-run      # show requests, no API calls
  uv run python src/query_llms.py --run-name pilot --smoke-test   # one live call per model
  uv run python src/query_llms.py --run-name pilot --limit 5      # 5 personas per state
  uv run python src/query_llms.py --run-name grid --persona-level 3 9 11 --persona-format list sentence \
      --prompt-style role_play prediction population

Re-running the same --run-name reuses valid responses and resumes the persisted
validation retry budget. Changed cached requests require a new run name.

Personas are drawn with replacement, so small states repeat respondents (e.g.
100 rows from 23 Alaskans). Each distinct respondent receives one initial query
per configuration, plus bounded retries if needed. Different respondents with
identical text remain separate jobs. If a respondent occurs four times, its
accepted answer contributes four times to the state average. Do not multiply by
commonweight again: survey weights already determined the sampling probabilities.
"""

import json
import os
import platform
import random
import re
import sys
import time
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import polars as pl
import requests
import yaml

from helper_query_validation import (MAX_VALIDATION_RETRIES, clean_metadata, current_records,
                                     probability_error, retry_invalid_queries)
from persona_text import (HELD_OUT, PERSONA_FORMATS, code_to_label, describe_persona,
                          load_value_labels)

DEFAULT_CONFIG = Path("config/query_config.yaml")
DEFAULT_PERSONAS = Path("data/personas/test")
OUTPUT_ROOT = Path("data/llm_responses")
QUESTION_NAME = "vote"
MAX_RETRIES = 5
TIMEOUT_S = 60
# MAX_RETRIES bounds HTTP transport attempts per call_api invocation. The helper's
# MAX_VALIDATION_RETRIES separately bounds additional response-validation attempts.


# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #
def args_parser():
    """Select the input sample and experimental combinations to query."""
    p = ArgumentParser(description="Query decision models with CES personas.")
    p.add_argument("--run-name", required=True, help="Output folder name under data/llm_responses/")
    p.add_argument("--output-root", type=Path, default=OUTPUT_ROOT,
                   help="Parent output folder (automation isolates each model here)")
    p.add_argument("--personas", default=str(DEFAULT_PERSONAS), help="Folder of per-state persona files")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--models", nargs="+", default=None, help="Model keys from the config (default: all)")
    p.add_argument("--persona-level", nargs="+", type=int, default=[11], help="3, 9 and/or 11")
    p.add_argument("--persona-format", nargs="+", default=["list"],
                   help="'list' (trait: value; ...) and/or 'sentence' (a White woman living in ...)")
    p.add_argument("--prompt-style", nargs="+", default=["prediction"], help="Keys under prompt_styles")
    p.add_argument("--news-file", nargs="+", default=None,
                   help="Text file(s) with a news summary; each one is a separate news condition")
    p.add_argument("--states", nargs="+", default=None, help="Only these states (default: all files)")
    p.add_argument("--limit", type=int, default=None, help="Only the first N personas per state")
    p.add_argument("--workers", type=int, default=8, help="Concurrent requests")
    p.add_argument("--dry-run", action="store_true", help="Print example requests; no API calls")
    p.add_argument("--smoke-test", action="store_true", help="Send one request per model and print it")
    return p.parse_args()


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader (KEY=value lines) so keys never live in code."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slug(option: str) -> str:
    """Convert an option label into its saved probability-column name."""
    return "p_" + re.sub(r"[^a-z0-9]+", "_", option.lower()).strip("_")


def load_personas(folder: Path, states: list[str] | None, limit: int | None) -> pl.DataFrame:
    """Read state samples and retain stable row identities for later expansion.

    persona_row identifies the original draw's position within its state file;
    caseid identifies the CES respondent, who may occupy several positions.
    An optional limit selects the first N draws, not N unique respondents.
    """
    frames = []
    for f in sorted(folder.iterdir()):
        # Metadata stays beside the data for tracking, but is not a Parquet input.
        if not f.is_file() or f.name.startswith(".") or f.suffix.lower() in (".yaml", ".yml"):
            continue
        state = f.stem
        if states and state not in states:
            continue
        df = pl.read_parquet(f).with_row_index("persona_row").with_columns(
            pl.lit(state).alias("state_file"))
        if limit:
            df = df.head(limit)
        frames.append(df)
    if not frames:
        sys.exit(f"No persona files found in {folder} (states={states})")
    return pl.concat(frames, how="vertical_relaxed")


# --------------------------------------------------------------------------- #
# Providers: build request body, parse response
# --------------------------------------------------------------------------- #
def build_payload(model_cfg: dict, context: str, question: str, options: dict) -> dict:
    """Express the same persona/question/options in the selected provider's schema.

    The context describes the persona; the question asks for the vote choice.
    Only this payload is sent, not the job's IDs, weights, or held-out outcomes.
    """
    provider = model_cfg["provider"]
    if provider == "openrouter_decisions":
        state = [context] if model_cfg.get("state_format", "list") == "list" else {"persona": context}
        return {
            "model": model_cfg["model"],
            "state": state,
            "questions": {
                QUESTION_NAME: {"type": "choice", "instructions": question, "criteria": options}
            },
        }
    if provider == "openai_decisions":
        return {
            "model": model_cfg["model"],
            "input": context,
            "questions": [{
                "type": "choice",
                "name": QUESTION_NAME,
                "instructions": question,
                "choices": [{"value": k, "description": v} for k, v in options.items()],
            }],
        }
    raise ValueError(f"Unknown provider: {provider}")


def _probabilities_to_dict(probs, options: list[str]) -> dict:
    """Convert supported response shapes into an option-to-probability mapping.

    Accept a named mapping, named entries in a list, or a list in request-option
    order. Require exactly one value per option. This normalizes STRUCTURE only:
    numerical values are checked separately and never rescaled to force a sum of 1.
    """
    if isinstance(probs, dict):
        if set(probs) != set(options):
            raise ValueError("Response probabilities must contain exactly the requested options.")
        return {o: probs[o] for o in options}
    if isinstance(probs, list) and probs:
        if isinstance(probs[0], dict):  # [{"value": "Democrat", "probability": 0.4}, ...]
            out = {}
            for item in probs:
                key = item.get("value", item.get("choice", item.get("label")))
                if key in out:
                    raise ValueError("Response contains a duplicate probability option.")
                out[key] = item.get("probability", item.get("p"))
            return _probabilities_to_dict(out, options)
        if len(probs) == len(options):  # plain list in the same order as the options
            return dict(zip(options, probs))
    raise ValueError("Response must provide one probability for every requested option.")


def parse_response(model_cfg: dict, body: dict, options: list[str]) -> dict:
    """Extract the vote vector and provider metadata, retaining all four options.

    choice/confidence are auxiliary outputs, not substitutes for the vector.
    A refusal has no vote probabilities and must not become "Would not vote".
    run_job checks numerical validity after parsing and retains the raw body.
    """
    provider = model_cfg["provider"]
    answers = body.get("answers", body)
    if provider == "openrouter_decisions":
        ans = answers[QUESTION_NAME]
    else:
        ans = next((a for a in answers if a.get("name") == QUESTION_NAME), answers[0])

    usage = body.get("usage") or {}
    parsed = {
        "model_snapshot": body.get("model"),
        "cost_usd": usage.get("cost"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
        "refused": ans.get("type") == "refusal",
        "choice": ans.get("choice"),
        "confidence": ans.get("confidence"),
    }
    probs = ({o: None for o in options} if parsed["refused"]
             else _probabilities_to_dict(ans.get("probabilities"), options))
    parsed.update({slug(o): probs[o] for o in options})
    return parsed


class RefusalError(Exception):
    """The model declined to answer. OpenRouter reports this as an HTTP error
    (e.g. 502 "OpenAI refused to answer question"), but it is an outcome, not a
    failure, so it is recorded as a refusal. Only the bounded post-batch
    validation stage may retry the original request."""


def call_api(model_cfg: dict, payload: dict) -> dict:
    """Send one logical request with bounded HTTP retries for transient failures.

    Return a decoded response or raise an exception for run_job to record.
    Network failures, rate limits, and eligible server errors use backoff. A
    recognizable refusal is recorded separately instead of treated as a transient
    server failure. Numerical validation/retries happen outside this function.
    """
    key = os.environ.get(model_cfg["api_key_env"])
    if not key:
        raise RuntimeError(f"{model_cfg['api_key_env']} is not set (add it to .env)")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(model_cfg["endpoint"], headers=headers, json=payload, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            err = f"connection error: {e}"
        else:
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}: {r.text[:500]}"
            if "refused to answer" in r.text.lower():
                raise RefusalError(err)
            if r.status_code not in (408, 409, 429) and r.status_code < 500:
                raise RuntimeError(err)  # bad request/auth: retrying won't help
        # Backoff with jitter reduces repeated collisions with the same rate limit.
        time.sleep(min(60, 2 ** attempt + random.random()))
    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts; last error: {err}")


# --------------------------------------------------------------------------- #
# Building the work list
# --------------------------------------------------------------------------- #
def build_jobs(personas: pl.DataFrame, cfg: dict, labels: dict, args) -> list[dict]:
    """Build unique respondent requests for every selected experimental combination.

    A configuration is model x persona level x prompt style x format x news.
    Deduplication is by respondent ID within a state, not by rendered prompt text.
    Each job keeps its exact payload and all sampled row positions for logging,
    cache checks, retries, and expansion back into the sampled population.
    """
    options = cfg["options"]
    model_keys = args.models or list(cfg["models"])
    news_conditions = [("none", None)]
    if args.news_file:
        news_conditions = [(Path(f).stem, Path(f).read_text().strip()) for f in args.news_file]

    # Fail before sending requests if a selection is unknown or would expose a
    # held-out outcome. Those outcomes may be stored alongside results, never
    # included among the characteristics shown to a model.
    for key in model_keys:
        if key not in cfg["models"]:
            sys.exit(f"Unknown model '{key}'. Options: {list(cfg['models'])}")
    for style in args.prompt_style:
        if style not in cfg["prompt_styles"]:
            sys.exit(f"Unknown prompt style '{style}'. Options: {list(cfg['prompt_styles'])}")
    for level in args.persona_level:
        if level not in cfg["persona_levels"]:
            sys.exit(f"Unknown persona level {level}. Options: {list(cfg['persona_levels'])}")
        if HELD_OUT.intersection(cfg["persona_levels"][level]):
            sys.exit(f"Persona level {level} includes a held-out outcome column")

    for fmt in args.persona_format:
        if fmt not in PERSONA_FORMATS:
            sys.exit(f"Unknown persona format '{fmt}'. Options: {list(PERSONA_FORMATS)}")
        for style in args.prompt_style:
            ctx = cfg["prompt_styles"][style]["context"]
            if isinstance(ctx, dict) and fmt not in ctx:
                sys.exit(f"Prompt style '{style}' has no context template for format '{fmt}'")

    # Example: the same caseid at rows [0, 4, 9] becomes one job whose persona_rows
    # list is [0, 4, 9]. Do not delete those repeated draws from the final average.
    people = {}
    for row in personas.to_dicts():
        person = (row["state_file"], row["caseid"])
        if person in people:
            people[person]["persona_rows"].append(row["persona_row"])
        else:
            people[person] = {**row, "persona_rows": [row["persona_row"]]}
    rows = list(people.values())

    # product creates every requested combination. Each receives a separate key,
    # so responses from different models/styles/formats cannot share an average.
    jobs = []
    for model_key, level, style, fmt, (news_label, news) in product(
            model_keys, args.persona_level, args.prompt_style, args.persona_format, news_conditions):
        model_cfg = cfg["models"][model_key]
        tmpl = cfg["prompt_styles"][style]
        # A context is either one template, or one template per persona format.
        context_tmpl = tmpl["context"][fmt] if isinstance(tmpl["context"], dict) else tmpl["context"]
        for row in rows:
            state = code_to_label("inputstate", row["inputstate"], labels)
            persona = describe_persona(row, cfg["persona_levels"][level], cfg["display_names"],
                                       labels, persona_format=fmt)
            fill = {"persona": persona, "state": state, **cfg["election"]}
            context = context_tmpl.format(**fill)
            if news:
                context = cfg["news_template"].format(news=news) + "\n\n" + context
            question = tmpl["question"].format(**fill)
            jobs.append({
                "key": f"{model_key}|{level}|{style}|{fmt}|{news_label}|{row['state_file']}|{row['caseid']}",
                "model_key": model_key,
                "model": model_cfg["model"],
                "persona_level": level,
                "prompt_style": style,
                "persona_format": fmt,
                "persona_text": persona,
                "news": news_label,
                "state": state,
                "persona_rows": row["persona_rows"],
                "caseid": row["caseid"],
                "commonweight": row["commonweight"],
                # Held-out outcomes: stored for validation, never sent to the model.
                "CC25_363": row.get("CC25_363"),
                "presvote24post": row.get("presvote24post"),
                "payload": build_payload(model_cfg, context, question, options),
            })
    return jobs


def run_job(job: dict, cfg: dict) -> dict:
    """Execute and classify one attempt; leave validation retry scheduling to the helper.

    Status meanings: ok = complete valid vector; invalid = a response arrived but
    its structure/numbers failed checks; refused = explicit model refusal;
    error = the request did not yield a usable response body. Return a record in
    every case so the collecting thread can append it to the audit log.
    """
    model_cfg = cfg["models"][job["model_key"]]
    record = {k: v for k, v in job.items()}
    record["requested_at"] = datetime.now(timezone.utc).isoformat()
    try:
        body = call_api(model_cfg, job["payload"])
        # Store before parsing: even an unparseable response must remain auditable.
        record["response"] = body
        record.update(parse_response(model_cfg, body, list(cfg["options"])))
        record["status"] = "refused" if record["refused"] else "ok"
        reason = probability_error(record, [slug(o) for o in cfg["options"]])
        if reason and record["status"] == "ok":
            record.update(status="invalid", error=reason)
    except RefusalError as e:
        record.update({"status": "refused", "refused": True, "error": str(e)})
    except Exception as e:
        record["status"] = "invalid" if "response" in record else "error"
        record["error"] = str(e)
    return record


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def read_records(path: Path) -> list[dict]:
    """Read attempts in append order; current_records selects the latest per job."""
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_results(out_dir: Path, cfg: dict, jobs: list[dict]) -> list[dict]:
    """Write all expected draws and state averages, returning metadata count rows.

    A job may serve several draws. Expand those positions before averaging so
    duplicate draws retain their intended contribution. Invalid/refused/error/
    unqueried rows remain in results for tracking, but all four probabilities are
    excluded together. Never average different options over different personas.

    n = expected sampled rows; n_valid + n_invalid = n. n_invalid includes every
    unresolved status, not just malformed numbers. n_unique_invalid counts CES
    respondents; invalid_percentage uses drawn rows. complete is false whenever
    any expected row is excluded. Averages are null when n_valid is zero.
    """
    latest = current_records(jobs, read_records(out_dir / "responses.jsonl"))
    p_cols = [slug(o) for o in cfg["options"]]
    keep = ["model_key", "model", "model_snapshot", "persona_level", "prompt_style",
            "persona_format", "news", "state", "persona_rows", "caseid", "commonweight",
            "CC25_363", "presvote24post", "status", "choice", "confidence", *p_cols,
            "cost_usd", "input_tokens", "output_tokens", "requested_at", "persona_text",
            "probability_valid", "validation_retry", "error"]
    rows = []
    for job in jobs:
        # Iterate the expected jobs, not only successful log entries. This keeps
        # missing/never-queried draws visible after an interrupted or aborted run.
        record = {**job, **latest.get(job["key"], {"status": "not_queried"})}
        reason = probability_error(record, p_cols)
        record["probability_valid"] = reason is None
        record.setdefault("validation_retry", 0)
        if reason:
            if record["status"] == "ok":
                record["status"] = "invalid"
            record["error"] = reason
            # Raw values remain in JSONL; invalid values cannot leak into averages
            # or force mixed string/numeric types in the tidy probability columns.
            record.update({column: None for column in p_cols})
        rows.append({k: record.get(k) for k in keep})
    calls = pl.DataFrame(rows, infer_schema_length=None).with_columns(pl.col(p_cols).cast(pl.Float64))
    # One record with persona_rows=[0, 4, 9] becomes three rows with the same answer.
    results = calls.explode("persona_rows").rename({"persona_rows": "persona_row"})
    results.write_parquet(out_dir / "results.parquet")

    config_cols = ["model_key", "persona_level", "prompt_style", "persona_format", "news"]
    # Use the SAME validity mask for every probability column. Group by both
    # state and configuration so different experimental conditions stay separate.
    # These are means of probabilities, not counts of the highest-ranked choice.
    summary = (results.group_by([*config_cols, "state"])
               .agg(pl.len().alias("n"), pl.col("caseid").n_unique().alias("n_unique"),
                    pl.col("probability_valid").sum().alias("n_valid"),
                    (~pl.col("probability_valid")).sum().alias("n_invalid"),
                    pl.col("caseid").filter(~pl.col("probability_valid")).n_unique().alias("n_unique_invalid"),
                    (pl.col("status") == "refused").mean().alias("refusal_rate"),
                    *[pl.col(c).filter(pl.col("probability_valid")).mean() for c in p_cols])
               .with_columns((100 * pl.col("n_invalid") / pl.col("n")).alias("invalid_percentage"),
                             (pl.col("n_invalid") == 0).alias("complete"))
               .sort([*config_cols, "state"]))
    summary.write_parquet(out_dir / "summary.parquet")
    n_invalid = int(summary["n_invalid"].sum())
    print(f"\nSaved {results.height} persona rows; {n_invalid} excluded from probability averages.")
    with pl.Config(tbl_rows=-1, tbl_cols=-1, tbl_width_chars=200):
        print("State probabilities averaged over valid sampled persona rows:")
        print(summary)
    return summary.select([*config_cols, "state", "n", "n_unique", "n_valid", "n_invalid",
                           "n_unique_invalid", "invalid_percentage", "complete"]).to_dicts()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    """Coordinate input selection, initial requests, bounded retries, and outputs."""
    # Step 1: build the complete expected work list before touching output files.
    args = args_parser()
    load_dotenv()
    cfg = yaml.safe_load(Path(args.config).read_text())
    labels = load_value_labels()
    personas = load_personas(Path(args.personas), args.states, args.limit)
    jobs = build_jobs(personas, cfg, labels, args)

    if args.dry_run:
        # Show one example per configuration, but count every unique job/draw.
        seen = set()
        for job in jobs:
            cfg_key = job["key"].rsplit("|", 2)[0]
            if cfg_key in seen:
                continue
            seen.add(cfg_key)
            print(f"\n=== {cfg_key} ({job['state']}, caseid {job['caseid']}, {len(job['persona_rows'])} rows) -> {cfg['models'][job['model_key']]['endpoint']}")
            print(json.dumps(job["payload"], indent=2))
        n_rows = sum(len(j["persona_rows"]) for j in jobs)
        print(f"\n{len(jobs)} requests would be sent across {len(seen)} configurations "
              f"(covering {n_rows} persona rows).")
        return

    if args.smoke_test:
        # A connectivity/schema probe only: no normal run log or summary is saved.
        seen_models = set()
        for job in jobs:
            if job["model_key"] in seen_models:
                continue
            seen_models.add(job["model_key"])
            rec = run_job(job, cfg)
            print(f"\n=== {job['model_key']} ({job['model']}): {rec['status']}")
            print(json.dumps(rec.get("response") or rec.get("error"), indent=2)[:3000])
            if rec["status"] != "error":
                print("Parsed:", {k: rec.get(k) for k in ["choice", "confidence",
                      *[slug(o) for o in cfg["options"]], "cost_usd"]})
        return

    # Step 2: reuse compatible saved attempts. The helper rejects changed request
    # contents or row memberships before any new requests can be sent.
    out_dir = Path(getattr(args, 'output_root', OUTPUT_ROOT)) / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "responses.jsonl"
    latest = current_records(jobs, read_records(jsonl))
    # Existing invalid/error records go to the bounded retry stage rather than
    # receiving an untracked new initial attempt every time the run is resumed.
    todo = [j for j in jobs if j["key"] not in latest]
    print(f"{len(jobs)} unique requests; {len(latest)} recorded; {len(todo)} initial requests to send.")

    # Record the invocation before querying, so even unfinished runs retain their
    # input arguments and start time. Finish/validation counts are added at the end.
    meta_path = out_dir / "run_metadata.json"
    meta = clean_metadata(json.loads(meta_path.read_text()) if meta_path.exists() else {"invocations": []})
    meta["invocations"].append({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "args": vars(args), "python": platform.python_version(),
        "n_requests": len(todo),
    })
    meta_path.write_text(json.dumps(meta, indent=2, default=str))

    # Step 3: send initial jobs concurrently; append/flush each completed attempt
    # from this collecting thread so workers do not compete to write the JSONL.
    n_ok = n_err = 0
    aborted = False
    first_errors = []
    with open(jsonl, "a") as f, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_job, job, cfg) for job in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            latest[rec["key"]] = rec
            if rec["status"] == "error":
                n_err += 1
                if len(first_errors) < 3:
                    first_errors.append(rec["error"])
                    print(f"  error ({rec['model_key']}): {rec['error'][:300]}")
                # Every early request failing usually means a bad key or request format.
                if n_ok == 0 and n_err >= 20:
                    print("First 20 requests all failed; stopping. Try --smoke-test.")
                    aborted = True
                    pool.shutdown(cancel_futures=True)
                    break
            elif probability_error(rec, [slug(o) for o in cfg["options"]]) is None:
                n_ok += 1
            else:
                n_err += 1
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done ({n_ok} valid, {n_err} unresolved)")

    # Step 4: after the initial batch, collect unresolved jobs into retry rounds.
    # Retries reuse the exact request and append every attempt for auditability.
    # Do not undo the early-stop protection by retrying a wholly broken setup.
    with open(jsonl, "a") as file:
        def save_record(record):
            file.write(json.dumps(record, default=str) + "\n")
            file.flush()

        _, validation = retry_invalid_queries(
            jobs, latest, [slug(o) for o in cfg["options"]],
            lambda job: run_job(job, cfg), save_record,
            workers=args.workers, max_retries=0 if aborted else MAX_VALIDATION_RETRIES)
    # Step 5: regenerate outputs from the latest saved attempts. Store exclusion
    # counts for every state/configuration, then mark the invocation as finished.
    validation["stopped_after_initial_errors"] = aborted
    validation["states"] = write_results(out_dir, cfg, jobs)
    validation["complete"] = all(state["complete"] for state in validation["states"])
    meta["validation"] = validation
    meta["invocations"][-1]["finished_at"] = datetime.now(timezone.utc).isoformat()
    meta["invocations"][-1]["validation_retry_requests"] = validation["retry_requests"]
    meta_path.write_text(json.dumps(meta, indent=2, default=str))


if __name__ == "__main__":
    main()
