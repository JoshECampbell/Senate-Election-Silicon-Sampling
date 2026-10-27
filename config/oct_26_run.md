
```bash
uv run python src/query_llms.py --run-name oct-26-all-models --personas data/personas/sample_100 --persona-level 9 --persona-format sentence --prompt-style role_play --models jev mercury decider
```

Daily automation uses these same query selections from `config/daily_run.yaml`,
with dated output folders such as `oct-28-no-luna`. The models are queried in
independent jobs, then combined into that folder. Edit the YAML to change the
automated selections; this Markdown file documents the original command.
