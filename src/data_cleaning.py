import polars as pl 
from pathlib import Path
from argparse import ArgumentParser


DEFAULT_PATH = Path("data/raw/raw_CES_2025_Common.tab")
DEFAULT_OUTPUT_DIR = Path("data/cleaned")
CES_COLUMNS = {
    # Identification
    "caseid": "Unique respondent identifier",

    # Demographics
    "race": "Racial or ethnic group",
    "gender4": "Gender: man, woman, non-binary, or other",
    "inputstate": "US state of residence",
    "educ": "Highest completed education level",
    "religpew": "Current religion or religious affiliation",
    "marstat": "Marital status",
    "sexuality": "Sexual orientation",
    "faminc_new": "Annual family income in the previous year",
    "birthyr": "Respondent year of birth",

    # Political characteristics
    "votereg": "Voter registration status",
    "pid3": "Three-point party identification",
    "pid7": "Seven-point party identification",
    "ideo5": "Five-point political ideology scale",

    # Election variables
    "CC25_363": "Intended US House vote in the 2026 election",
    "presvote24post": "Reported presidential vote in 2024",

    # Population weighting
    "commonweight": "Common Content survey weight",
}



def args_parser(): 
    parser = ArgumentParser()
    parser.add_argument("--raw-path", help= "Path for raw data to be cleaned (str)", 
                         type=str, default=DEFAULT_PATH)
    parser.add_argument("--output-dir",help= "Path for output (str)", 
                         type=str, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()

def clean_raw():
    args = args_parser() 

    # Lazy read in to save memory 
    lazy_df = pl.scan_csv(args.raw_path, separator="\t") 
    query = ( 
        lazy_df.select([cols for cols in CES_COLUMNS])
    )

    df = query.collect()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cleaned_CES_data.parquet"
    df.write_parquet(output_path, use_pyarrow=True)


    print(f"Raw data cleaned and outputted to: {output_path}, Shape = {df.shape}")

if __name__ == "__main__": 
    clean_raw()