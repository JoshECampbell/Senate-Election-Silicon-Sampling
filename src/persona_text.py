"""Turn a CES persona row into the text description given to the model."""

from pathlib import Path

import yaml

DEFAULT_LABELS_PATH = Path("config/ces_codes/ces25_value_labels.yaml")

# Outcomes we evaluate against. They must never appear in a prompt.
HELD_OUT = {"CC25_363", "presvote24post"}


def load_value_labels(path: Path | str = DEFAULT_LABELS_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["variables"]


def code_to_label(field: str, value, labels: dict) -> str | None:
    """Return the text label for a coded value, or None if missing/skipped."""
    if value is None:
        return None
    spec = labels[field]
    code = int(value)
    if code in spec.get("missing", []):
        return None
    return spec["codes"].get(code)


def describe_persona(row: dict, fields: list[str], display_names: dict, labels: dict) -> str:
    """Build e.g. 'race/ethnicity: White; gender: Woman; state of residence: Georgia'.

    Characteristics that are missing or skipped for this respondent are left out.
    """
    leaked = HELD_OUT.intersection(fields)
    if leaked:
        raise ValueError(f"Held-out outcome(s) {sorted(leaked)} must not be in a persona")

    parts = []
    for field in fields:
        label = code_to_label(field, row.get(field), labels)
        if label is not None:
            parts.append(f"{display_names.get(field, field)}: {label}")
    return "; ".join(parts)
