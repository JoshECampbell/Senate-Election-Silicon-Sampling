"""Turn a CES persona row into the text description given to the model.

Two formats are supported, so the wording of the persona can be tested as an
experimental variable:

  list      "race/ethnicity: White; gender: Woman; state of residence: Alabama"
  sentence  "a White woman living in Alabama who has a 4-year college degree, ..."

The sentence format is a noun phrase, so prompt templates can wrap it as
"You are {persona}." or "Consider {persona}."
"""

from pathlib import Path

import yaml

DEFAULT_LABELS_PATH = Path("config/ces_codes/ces25_value_labels.yaml")

# Outcomes we evaluate against. They must never appear in a prompt.
HELD_OUT = {"CC25_363", "presvote24post"}

PERSONA_FORMATS = ("list", "sentence")


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


def _check_fields(fields: list[str]) -> None:
    leaked = HELD_OUT.intersection(fields)
    if leaked:
        raise ValueError(f"Held-out outcome(s) {sorted(leaked)} must not be in a persona")


# --------------------------------------------------------------------------- #
# List format
# --------------------------------------------------------------------------- #
def describe_persona_list(row: dict, fields: list[str], display_names: dict, labels: dict) -> str:
    """'race/ethnicity: White; gender: Woman; state of residence: Georgia'.

    Characteristics that are missing or skipped for this respondent are left out.
    """
    _check_fields(fields)
    parts = []
    for field in fields:
        label = code_to_label(field, row.get(field), labels)
        if label is not None:
            parts.append(f"{display_names.get(field, field)}: {label}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Sentence format
# --------------------------------------------------------------------------- #
# Natural-language wording for each CES code. Codes not listed here (e.g. race
# "Other", sexuality "Other") are left out of the sentence rather than forced
# into awkward phrasing; missing/skipped codes are always left out.
RACE_ADJ = {
    1: "White", 2: "Black", 3: "Hispanic", 4: "Asian American", 5: "Native American",
    6: "multiracial", 8: "Middle Eastern",
}
GENDER_NOUN = {1: "man", 2: "woman", 3: "non-binary person", 4: "person"}
PRONOUN = {1: "his", 2: "her"}  # anyone else: "their"

# Each clause follows "who", so it is written in the third person singular.
CLAUSES = {
    "educ": {
        1: "did not graduate from high school",
        2: "has a high school diploma",
        3: "attended some college but has no degree",
        4: "has a 2-year college degree",
        5: "has a 4-year college degree",
        6: "has a postgraduate degree",
    },
    "religpew": {
        1: "is Protestant", 2: "is Roman Catholic", 3: "is Mormon",
        4: "is Eastern or Greek Orthodox", 5: "is Jewish", 6: "is Muslim",
        7: "is Buddhist", 8: "is Hindu", 9: "is an atheist", 10: "is agnostic",
        11: "has no religion in particular", 12: "follows another religion",
    },
    "marstat": {
        1: "is married", 2: "is separated", 3: "is divorced", 4: "is widowed",
        5: "has never been married", 6: "is in a domestic or civil partnership",
    },
    "sexuality": {1: "is straight", 2: "is a lesbian", 3: "is gay", 4: "is bisexual"},
    "votereg": {1: "is registered to vote", 2: "is not registered to vote"},
    "pid7": {
        1: "identifies as a strong Democrat",
        2: "identifies as a Democrat (not a strong one)",
        3: "is an independent who leans Democrat",
        4: "is an independent",
        5: "is an independent who leans Republican",
        6: "identifies as a Republican (not a strong one)",
        7: "identifies as a strong Republican",
    },
    "ideo5": {
        1: "describes {pronoun} political views as very liberal",
        2: "describes {pronoun} political views as liberal",
        3: "describes {pronoun} political views as moderate",
        4: "describes {pronoun} political views as conservative",
        5: "describes {pronoun} political views as very conservative",
    },
}


def _code(row: dict, field: str, labels: dict) -> int | None:
    """The respondent's code for a field, or None if missing/skipped."""
    if code_to_label(field, row.get(field), labels) is None:
        return None
    return int(row[field])


def _a_or_an(word: str) -> str:
    return "an" if word[0].lower() in "aeiou" else "a"


def describe_persona_sentence(row: dict, fields: list[str], labels: dict) -> str:
    """'a White woman living in Alabama who has a 4-year college degree, is
    Protestant, is married, ... and identifies as a strong Republican'."""
    _check_fields(fields)

    gender = _code(row, "gender4", labels) if "gender4" in fields else None
    race = _code(row, "race", labels) if "race" in fields else None
    noun = GENDER_NOUN.get(gender, "person")
    adj = RACE_ADJ.get(race)
    head = f"{adj} {noun}" if adj else noun
    phrase = f"{_a_or_an(head)} {head}"

    if "inputstate" in fields and _code(row, "inputstate", labels) is not None:
        phrase += f" living in {code_to_label('inputstate', row['inputstate'], labels)}"

    pronoun = PRONOUN.get(gender, "their")
    clauses = []
    for field in fields:
        if field in ("race", "gender4", "inputstate"):
            continue
        code = _code(row, field, labels)
        if code is None:
            continue
        if field == "faminc_new":
            income = code_to_label(field, code, labels).replace(" - ", " to ")
            income = income[0].lower() + income[1:]  # "Less than $10,000" -> "less than ..."
            clauses.append(f"has an annual family income of {income}")
        elif code in CLAUSES.get(field, {}):
            clauses.append(CLAUSES[field][code].format(pronoun=pronoun))

    if not clauses:
        return phrase
    if len(clauses) == 1:
        return f"{phrase} who {clauses[0]}"
    return f"{phrase} who {', '.join(clauses[:-1])}, and {clauses[-1]}"


# --------------------------------------------------------------------------- #
def describe_persona(row: dict, fields: list[str], display_names: dict, labels: dict,
                     persona_format: str = "list") -> str:
    if persona_format == "list":
        return describe_persona_list(row, fields, display_names, labels)
    if persona_format == "sentence":
        return describe_persona_sentence(row, fields, labels)
    raise ValueError(f"Unknown persona format '{persona_format}'. Options: {PERSONA_FORMATS}")
