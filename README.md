# Senate-Election-Silicon-Sampling

## CES Common Content 2025 raw data

`scripts/download_ces_common_content_2025.py` downloads the released Cumulative
CES Common Content v12.0 Feather file from Harvard Dataverse, verifies its
published MD5 checksum, and saves the unmodified 2025 subset as
`data/raw/ces_common_content_2025_raw.parquet`. Its adjacent JSON metadata
marks the file as `raw`. Parquet is the project's standard data format.

Install the dependency, then download and test the data:

```sh
python -m pip install -r requirements.txt
python scripts/download_ces_common_content_2025.py
python tests/test_ces_common_content_2025.py
```

The integrity test requires the raw Parquet file to exist and verifies that it
has exactly 17,000 unique, non-missing `case_id` respondents, all from 2025.
