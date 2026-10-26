# CES 2025 codebook and data preparation

This reference describes the project's CES 2025 Common Content variables and the implemented raw-to-cleaned workflow. Response labels and missing-code rules are transcribed from [ces25_value_labels.yaml](../config/ces_codes/ces25_value_labels.yaml); that YAML file remains the machine-readable source of truth. This is a project codebook, not an independently verified copy of the full official CES codebook. It covers all 17 retained variables.

## Raw-to-cleaned process

1. **Download the raw file.** [raw_data_pull.py](../src/raw_data_pull.py) downloads Harvard Dataverse file ID `13600926` from `https://dataverse.harvard.edu/api/access/datafile/13600926`, checks the HTTP response, and streams it to `data/raw/raw_CES_2025_Common.tab`. The script does not perform a checksum check or write download metadata.
2. **Read the tab-separated data.** [data_cleaning.py](../src/data_cleaning.py) uses Polars `scan_csv(..., separator="\t")` with default type inference.
3. **Select the analysis variables.** The script keeps the 17 columns listed below, in the order shown. Column names and response codes are retained.
4. **Write the cleaned file.** The selected data are collected and written with `write_parquet(..., use_pyarrow=True)` to `data/cleaned/cleaned_CES_data.parquet`. The output directory is created if needed.

At this stage, ?cleaned? means column selection and conversion to Parquet. The script does not filter respondents or states, remove duplicates, impute missing values, replace special missing codes with nulls, recode categories, derive age, or normalize weights. Ordinary CSV parsing and type inference still apply.

### Verification of the existing files

Checked on October 21, 2026 using the local raw and cleaned files:

| Check | Result |
| --- | --- |
| Raw dimensions | 17,000 respondents ? 341 columns |
| Cleaned dimensions | 17,000 respondents ? 17 columns |
| Cleaned data equal the same columns selected from raw | Yes, including row order and values |
| Unique cleaned `caseid` values | 17,000 |
| Null cleaned `caseid` values | 0 |

These observations describe the files checked; they are not validation steps enforced by the cleaning script. The README's references to a cumulative Feather download and other script paths do not describe the current scripts documented here.

### Commands

Run from the repository root:

```sh
uv run python src/raw_data_pull.py
uv run python src/data_cleaning.py
```

For an alternative input or output folder:

```sh
uv run python src/data_cleaning.py --raw-path path/to/input.tab --output-dir path/to/output
```

These commands write to their output paths and can replace existing files.

## Variable overview

| CES variable | Meaning | Role in this project |
| --- | --- | --- |
| `caseid` | Unique respondent identifier (verify name in released data) | Respondent identifier; not a prompt characteristic |
| `race` | Racial or ethnic group | Prompt characteristic in persona levels 3, 9, 11 |
| `gender4` | Gender | Prompt characteristic in persona levels 3, 9, 11 |
| `inputstate` | State of residence (numeric codes correspond to state FIPS) | Prompt characteristic in persona levels 3, 9, 11 |
| `educ` | Highest level of education completed | Prompt characteristic in persona levels 9, 11 |
| `religpew` | Present religion, if any | Prompt characteristic in persona levels 9, 11 |
| `marstat` | Marital status | Prompt characteristic in persona levels 9, 11 |
| `sexuality` | Sexual orientation | Prompt characteristic in persona levels 9, 11 |
| `faminc_new` | Family annual income in the previous year | Prompt characteristic in persona levels 9, 11 |
| `birthyr` | Year of birth | Retained for analysis; not in the configured persona levels |
| `votereg` | Registered to vote | Prompt characteristic in persona levels 9, 11 |
| `pid3` | Three-category party identification (also allows other and unsure) | Retained for analysis; not in the configured persona levels |
| `pid7` | Seven-point party identification | Prompt characteristic in persona levels 11 |
| `ideo5` | Political ideology | Prompt characteristic in persona levels 11 |
| `CC25_363` | Intended party vote for US House in 2026 | Held-out outcome: House vote intention, not Senate intention |
| `presvote24post` | Self-reported vote for president in 2024 | Held-out outcome: reported 2024 presidential vote |
| `commonweight` | Common Content survey weight (verify name and usage in released data) | Within-state sampling weight; not a prompt characteristic |

## Response codes

?Missing / omitted? identifies codes listed in the YAML `missing` field. These numeric codes remain in the cleaned file. During persona text construction, [persona_text.py](../src/persona_text.py) omits a characteristic if its value is null, listed as missing, or has no matching code label. This does not remove the respondent. For held-out outcomes, the table records the configured missing codes; the persona formatter never includes those outcomes in prompts.

### `caseid` ? Unique respondent identifier (verify name in released data)

An identifier, not a response category. Preserve it to link records; numeric differences between IDs have no substantive meaning.

### `race` ? Racial or ethnic group

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | White | No |
| 2 | Black or African-American | No |
| 3 | Hispanic or Latino | No |
| 4 | Asian or Asian-American | No |
| 5 | Native American | No |
| 6 | Two or more races | No |
| 7 | Other | No |
| 8 | Middle Eastern | No |
| 98 | Skipped | Yes |
| 99 | Not Asked | Yes |

### `gender4` ? Gender

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Man | No |
| 2 | Woman | No |
| 3 | Non-binary | No |
| 4 | Other | No |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `inputstate` ? State of residence (numeric codes correspond to state FIPS)

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Alabama | No |
| 2 | Alaska | No |
| 4 | Arizona | No |
| 5 | Arkansas | No |
| 6 | California | No |
| 8 | Colorado | No |
| 9 | Connecticut | No |
| 10 | Delaware | No |
| 11 | District of Columbia | No |
| 12 | Florida | No |
| 13 | Georgia | No |
| 15 | Hawaii | No |
| 16 | Idaho | No |
| 17 | Illinois | No |
| 18 | Indiana | No |
| 19 | Iowa | No |
| 20 | Kansas | No |
| 21 | Kentucky | No |
| 22 | Louisiana | No |
| 23 | Maine | No |
| 24 | Maryland | No |
| 25 | Massachusetts | No |
| 26 | Michigan | No |
| 27 | Minnesota | No |
| 28 | Mississippi | No |
| 29 | Missouri | No |
| 30 | Montana | No |
| 31 | Nebraska | No |
| 32 | Nevada | No |
| 33 | New Hampshire | No |
| 34 | New Jersey | No |
| 35 | New Mexico | No |
| 36 | New York | No |
| 37 | North Carolina | No |
| 38 | North Dakota | No |
| 39 | Ohio | No |
| 40 | Oklahoma | No |
| 41 | Oregon | No |
| 42 | Pennsylvania | No |
| 44 | Rhode Island | No |
| 45 | South Carolina | No |
| 46 | South Dakota | No |
| 47 | Tennessee | No |
| 48 | Texas | No |
| 49 | Utah | No |
| 50 | Vermont | No |
| 51 | Virginia | No |
| 53 | Washington | No |
| 54 | West Virginia | No |
| 55 | Wisconsin | No |
| 56 | Wyoming | No |
| 98 | Skipped | Yes |
| 99 | Not Asked | Yes |

### `educ` ? Highest level of education completed

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Did not graduate from high school | No |
| 2 | High school graduate | No |
| 3 | Some college, but no degree | No |
| 4 | 2-year college degree | No |
| 5 | 4-year college degree | No |
| 6 | Postgraduate degree | No |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `religpew` ? Present religion, if any

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Protestant | No |
| 2 | Roman Catholic | No |
| 3 | Mormon | No |
| 4 | Eastern or Greek Orthodox | No |
| 5 | Jewish | No |
| 6 | Muslim | No |
| 7 | Buddhist | No |
| 8 | Hindu | No |
| 9 | Atheist | No |
| 10 | Agnostic | No |
| 11 | Nothing in particular | No |
| 12 | Something else | No |
| 98 | Skipped | Yes |
| 99 | Not Asked | Yes |

### `marstat` ? Marital status

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Married | No |
| 2 | Separated | No |
| 3 | Divorced | No |
| 4 | Widowed | No |
| 5 | Never married | No |
| 6 | Domestic / civil partnership | No |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `sexuality` ? Sexual orientation

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Heterosexual / straight | No |
| 2 | Lesbian / gay woman | No |
| 3 | Gay man | No |
| 4 | Bisexual | No |
| 5 | Other | No |
| 6 | Prefer not to say | Yes |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `faminc_new` ? Family annual income in the previous year

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Less than $10,000 | No |
| 2 | $10,000 - $19,999 | No |
| 3 | $20,000 - $29,999 | No |
| 4 | $30,000 - $39,999 | No |
| 5 | $40,000 - $49,999 | No |
| 6 | $50,000 - $59,999 | No |
| 7 | $60,000 - $69,999 | No |
| 8 | $70,000 - $79,999 | No |
| 9 | $80,000 - $99,999 | No |
| 10 | $100,000 - $119,999 | No |
| 11 | $120,000 - $149,999 | No |
| 12 | $150,000 - $199,999 | No |
| 13 | $200,000 - $249,999 | No |
| 14 | $250,000 - $349,999 | No |
| 15 | $350,000 - $499,999 | No |
| 16 | $500,000 or more | No |
| 97 | Prefer not to say | Yes |
| 998 | Skipped | Yes |
| 999 | Not Asked | Yes |

### `birthyr` ? Year of birth

Numeric year of birth, not an age or category code. No special missing codes are defined in the project YAML.

### `votereg` ? Registered to vote

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Yes | No |
| 2 | No | No |
| 3 | Don't know | Yes |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `pid3` ? Three-category party identification (also allows other and unsure)

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Democrat | No |
| 2 | Republican | No |
| 3 | Independent | No |
| 4 | Other | No |
| 5 | Not sure | Yes |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `pid7` ? Seven-point party identification

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Strong Democrat | No |
| 2 | Not very strong Democrat | No |
| 3 | Lean Democrat | No |
| 4 | Independent | No |
| 5 | Lean Republican | No |
| 6 | Not very strong Republican | No |
| 7 | Strong Republican | No |
| 8 | Not sure | Yes |
| 9 | Don't know | Yes |
| 98 | Skipped | Yes |
| 99 | Not Asked | Yes |

### `ideo5` ? Political ideology

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Very liberal | No |
| 2 | Liberal | No |
| 3 | Moderate | No |
| 4 | Conservative | No |
| 5 | Very conservative | No |
| 6 | Not sure | Yes |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `CC25_363` ? Intended party vote for US House in 2026

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Do not intend to vote in the 2026 election | No |
| 2 | Likely to vote for the Democratic US House candidate | No |
| 3 | Likely to vote for the Republican US House candidate | No |
| 4 | Not sure | Yes |
| 8 | Skipped | Yes |
| 9 | Not Asked | Yes |

### `presvote24post` ? Self-reported vote for president in 2024

| Code | Human-readable response | Missing / omitted |
| --- | --- | --- |
| 1 | Kamala Harris | No |
| 2 | Donald Trump | No |
| 3 | Robert F. Kennedy Jr. | No |
| 4 | Jill Stein | No |
| 5 | Cornel West | No |
| 6 | Chase Oliver | No |
| 8 | Other | No |
| 9 | Did not vote for president | No |
| 98 | Skipped | Yes |
| 99 | Not Asked | Yes |

### `commonweight` ? Common Content survey weight (verify name and usage in released data)

Numeric Common Content survey weight. No categorical labels or special missing codes are defined in the project YAML.

## Subsequent persona preparation

These steps happen after cleaning, in [create_personas.py](../src/create_personas.py):

1. Read the cleaned Parquet file and restrict it to the 35 state codes in the script's `SENATE_STATES_2026` mapping. This filter does not change the cleaned file.
2. Within each state, calculate each respondent's draw probability as `commonweight / sum(commonweight)` for that state's respondents.
3. Draw the requested number of respondents **with replacement**, using NumPy's random generator. Defaults are seed `42` and `100` draws per state. A respondent can therefore appear more than once.
4. Preserve all 17 columns in each sampled row and save a Parquet file named for the state, without a file extension, under `data/personas/<run-name>/`.
5. Write `persona_config.yaml` with the input path, seed, draw count, and each state's available respondent count and `samples / population` ratio. Because sampling uses replacement, this ratio is not the fraction of unique respondents selected.

Example:

```sh
uv run python src/create_personas.py --run-name example --seed 42 --samples 100
```

The sampler uses the weights directly; it does not implement repairs for missing, negative, or zero-total weights. The defaults above describe the script, not verified settings for every existing persona run.

## Conversion into model prompts

[query_config.yaml](../config/query_config.yaml) defines these persona levels:

- **3 characteristics:** `race`, `gender4`, `inputstate`.
- **9 characteristics:** `race`, `gender4`, `inputstate`, `educ`, `religpew`, `marstat`, `sexuality`, `votereg`, `faminc_new`.
- **11 characteristics:** `race`, `gender4`, `inputstate`, `educ`, `religpew`, `marstat`, `sexuality`, `votereg`, `faminc_new`, `pid7`, `ideo5`.

Numeric codes are translated to the labels above when creating prompt text. For example, `race = 1` becomes ?race/ethnicity: White? and `gender4 = 2` becomes ?gender: Woman?. Missing characteristics are omitted, so a nominal 11-characteristic persona may contain fewer than 11 characteristics.

`CC25_363` and `presvote24post` are held out and explicitly blocked from persona descriptions. The configured model question concerns the **2026 US Senate election**, whereas `CC25_363` measures **2026 US House vote intention**. They are different outcomes. The project's label file notes that no direct 2026 Senate vote-intention question is present in the questionnaire. The four model response options?Democrat, Republican, Third party, and Would not vote?are defined separately in the query config; the cleaning script does not map the held-out outcomes to those options.
