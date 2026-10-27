"""Download the raw CES 2025 Common Content file.

Workflow: create data/raw -> stream the Dataverse response -> save the original
tab-separated file as raw_CES_2025_Common.tab. This replaces that file if present.
Usage (repository root): uv run python src/raw_data_pull.py
"""

import requests
from pathlib import Path

FILE_ID = 13600926 # CES Common 2025 Code 
DATA_URL = f"https://dataverse.harvard.edu/api/access/datafile/{FILE_ID}"
OUTPUT_DIR = Path("data/raw")

def pull_raw(URL: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with requests.get(URL, stream=True, timeout=120) as r:
        r.raise_for_status()

        with open(OUTPUT_DIR / "raw_CES_2025_Common.tab", "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    print("CES 2025 Common Content downloaded.")

if __name__ == "__main__":
    pull_raw(DATA_URL)
