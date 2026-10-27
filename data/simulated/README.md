# Artificial cleaned-CES fixture

`cleaned_CES_data.parquet` contains 128 generated rows with the real cleaned
file's 17 columns and storage types. It includes allowed codebook responses and
some null answers, with artificial IDs, adult birth years and positive weights.
It contains no real respondents and is not a representative research dataset.

Regenerate from the repository root with `uv run python src/simulate_cleaned_ces.py`.
The default seed is 42. Test it with
`uv run python -m unittest discover -s test -p 'test_simulated_ces_data.py' -v`.
