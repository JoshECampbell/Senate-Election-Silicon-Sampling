"""Query decision models for synthetic 2026 Senate vote choices from CES personas.

Each request gives a model one persona (context) and one four-option choice
question. Decision models return a probability for every option, and we store
the full distribution, not just the top pick.

Supported providers (set in config/query_config.yaml):
  - openrouter_decisions: TypeSafe Jev via OpenRouter's Decisions API
  - openai_decisions:     OpenAI's Decisions API (gpt-6-luna)

Outputs go to data/llm_responses/<run-name>/:
  responses.jsonl     every request + raw response, appended as it runs (resumable)
  results.parquet     one tidy row per persona x configuration
  summary.parquet     mean probabilities by state x configuration
  run_metadata.json   config snapshot, arguments, git commit, timestamps

Typical use:
  uv run python src/query_llms.py --run-name pilot --dry-run      # show requests, no API calls
  uv run python src/query_llms.py --run-name pilot --smoke-test   # one live call per model
  uv run python src/query_llms.py --run-name pilot --limit 5      # 5 personas per state
  uv run python src/query_llms.py --run-name grid --persona-level 3 9 11 --persona-format list sentence \
      --prompt-style role_play prediction population

Re-running the same --run-name skips anything already answered, so an
interrupted run can simply be restarted.
"""

import json
import os
import platform
import random
import re
import subprocess
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

from persona_text import (HELD_OUT, PERSONA_FORMATS, code_to_label, describe_persona,
                          load_value_labels)

DEFAULT_CONFIG = Path("config/query_config.yaml")
DEFAULT_PERSONAS = Path("data/personas/test")
OUTPUT_ROOT = Path("data/llm_responses")
QUESTION_NAME = "vote"
MAX_RETRIES = 5
TIMEOUT_S = 60


# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #
def args_parser():
    p = ArgumentParser(description="Query decision models with CES personas.")
    p.add_argument("--run-name", required=True, help="Output folder name under data/llm_responses/")
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
    return "p_" + re.sub(r"[^a-z0-9]+", "_", option.lower()).strip("_")


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def load_personas(folder: Path, states: list[str] | None, limit: int | None) -> pl.DataFrame:
    """Read each per-state persona file and tag rows with state and row number."""
    frames = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name.startswith("."):
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
    """Normalise the different shapes providers use for per-option probabilities."""
    if isinstance(probs, dict):
        return {o: probs.get(o) for o in options}
    if isinstance(probs, list) and probs:
        if isinstance(probs[0], dict):  # [{"value": "Democrat", "probability": 0.4}, ...]
            out = {}
            for item in probs:
                key = item.get("value", item.get("choice", item.get("label")))
                out[key] = item.get("probability", item.get("p"))
            return {o: out.get(o) for o in options}
        if len(probs) == len(options):  # plain list in the same order as the options
            return dict(zip(options, probs))
    return {o: None for o in options}


def parse_response(model_cfg: dict, body: dict, options: list[str]) -> dict:
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
        "refused": ans.get("type") == "refusal",
        "choice": ans.get("choice"),
        "confidence": ans.get("confidence"),
    }
    probs = _probabilities_to_dict(ans.get("probabilities"), options)
    parsed.update({slug(o): probs[o] for o in options})
    return parsed


class RefusalError(Exception):
    """The model declined to answer. OpenRouter reports this as an HTTP error
    (e.g. 502 "OpenAI refused to answer question"), but it is an outcome, not a
    failure, so it is recorded as a refusal and never retried."""


def call_api(model_cfg: dict, payload: dict) -> dict:
    """POST with retries on rate limits, server errors and dropped connections."""
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
        time.sleep(min(60, 2 ** attempt + random.random()))
    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts; last error: {err}")


# --------------------------------------------------------------------------- #
# Building the work list
# --------------------------------------------------------------------------- #
def build_jobs(personas: pl.DataFrame, cfg: dict, labels: dict, args) -> list[dict]:
    options = cfg["options"]
    model_keys = args.models or list(cfg["models"])
    news_conditions = [("none", None)]
    if args.news_file:
        news_conditions = [(Path(f).stem, Path(f).read_text().strip()) for f in args.news_file]

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

    jobs = []
    rows = personas.to_dicts()
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
                "key": f"{model_key}|{level}|{style}|{fmt}|{news_label}|{row['state_file']}|{row['persona_row']}",
                "model_key": model_key,
                "model": model_cfg["model"],
                "persona_level": level,
                "prompt_style": style,
                "persona_format": fmt,
                "persona_text": persona,
                "news": news_label,
                "state": state,
                "persona_row": row["persona_row"],
                "caseid": row["caseid"],
                "commonweight": row["commonweight"],
                # Held-out outcomes: stored for validation, never sent to the model.
                "CC25_363": row.get("CC25_363"),
                "presvote24post": row.get("presvote24post"),
                "payload": build_payload(model_cfg, context, question, options),
            })
    return jobs


def run_job(job: dict, cfg: dict) -> dict:
    model_cfg = cfg["models"][job["model_key"]]
    record = {k: v for k, v in job.items()}
    record["requested_at"] = datetime.now(timezone.utc).isoformat()
    try:
        body = call_api(model_cfg, job["payload"])
        record["response"] = body
        record.update(parse_response(model_cfg, body, list(cfg["options"])))
        record["status"] = "refused" if record["refused"] else "ok"
    except RefusalError as e:
        record.update({"status": "refused", "refused": True, "error": str(e)})
    except Exception as e:
        record["status"] = "error"
        record["error"] = str(e)
    return record


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_results(out_dir: Path, cfg: dict) -> None:
    records = read_records(out_dir / "responses.jsonl")
    latest = {}
    for rec in records:  # keep the last attempt per key
        latest[rec["key"]] = rec
    done = [r for r in latest.values() if r["status"] in ("ok", "refused")]
    if not done:
        print("No successful responses yet; nothing to summarise.")
        return

    p_cols = [slug(o) for o in cfg["options"]]
    keep = ["model_key", "model", "model_snapshot", "persona_level", "prompt_style",
            "persona_format", "news", "state", "persona_row", "caseid", "commonweight",
            "CC25_363", "presvote24post", "status", "choice", "confidence", *p_cols,
            "cost_usd", "input_tokens", "requested_at", "persona_text"]
    for r in done:
        r.setdefault("persona_format", "list")  # runs made before formats existed
    results = pl.DataFrame([{k: r.get(k) for k in keep} for r in done], infer_schema_length=None)
    results.write_parquet(out_dir / "results.parquet")

    config_cols = ["model_key", "persona_level", "prompt_style", "persona_format", "news"]
    summary = (results.group_by([*config_cols, "state"])
               .agg(pl.len().alias("n"), (pl.col("status") == "refused").mean().alias("refusal_rate"),
                    *[pl.col(c).mean() for c in p_cols])
               .sort([*config_cols, "state"]))
    summary.write_parquet(out_dir / "summary.parquet")

    overall = (results.group_by(config_cols)
               .agg(pl.len().alias("n"),
                    (pl.col("status") == "refused").mean().round(3).alias("refusal_rate"),
                    *[pl.col(c).mean().round(3) for c in p_cols],
                    pl.col("cost_usd").sum().alias("cost_usd"))
               .sort(config_cols))
    n_err = sum(r["status"] == "error" for r in latest.values())
    print(f"\nSaved {results.height} responses to {out_dir / 'results.parquet'}"
          + (f" ({n_err} still failing; re-run to retry)" if n_err else ""))
    with pl.Config(tbl_rows=-1, tbl_cols=-1, tbl_width_chars=200):
        print("Mean probabilities across all states (unweighted average of states):")
        print(overall)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    args = args_parser()
    load_dotenv()
    cfg = yaml.safe_load(Path(args.config).read_text())
    labels = load_value_labels()
    personas = load_personas(Path(args.personas), args.states, args.limit)
    jobs = build_jobs(personas, cfg, labels, args)

    if args.dry_run:
        seen = set()
        for job in jobs:
            cfg_key = job["key"].rsplit("|", 2)[0]
            if cfg_key in seen:
                continue
            seen.add(cfg_key)
            print(f"\n=== {cfg_key} ({job['state']}, row {job['persona_row']}) -> {cfg['models'][job['model_key']]['endpoint']}")
            print(json.dumps(job["payload"], indent=2))
        print(f"\n{len(jobs)} requests would be sent across {len(seen)} configurations.")
        return

    if args.smoke_test:
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

    out_dir = OUTPUT_ROOT / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "responses.jsonl"
    already = {r["key"] for r in read_records(jsonl) if r["status"] in ("ok", "refused")}
    todo = [j for j in jobs if j["key"] not in already]
    print(f"{len(jobs)} requests in this run; {len(already & {j['key'] for j in jobs})} already done; "
          f"{len(todo)} to send.")

    meta_path = out_dir / "run_metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"invocations": []}
    meta["config"] = cfg
    meta["invocations"].append({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "args": vars(args), "git_commit": git_commit(), "python": platform.python_version(),
        "n_requests": len(todo),
    })
    meta_path.write_text(json.dumps(meta, indent=2, default=str))

    n_ok = n_err = 0
    first_errors = []
    with open(jsonl, "a") as f, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_job, job, cfg) for job in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            if rec["status"] == "error":
                n_err += 1
                if len(first_errors) < 3:
                    first_errors.append(rec["error"])
                    print(f"  error ({rec['model_key']}): {rec['error'][:300]}")
                # Every early request failing usually means a bad key or request format.
                if n_ok == 0 and n_err >= 20:
                    print("First 20 requests all failed; stopping. Try --smoke-test.")
                    pool.shutdown(cancel_futures=True)
                    break
            else:
                n_ok += 1
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done ({n_ok} ok, {n_err} errors)")

    write_results(out_dir, cfg)


if __name__ == "__main__":
    main()
