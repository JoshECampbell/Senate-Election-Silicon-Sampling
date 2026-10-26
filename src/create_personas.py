import polars as pl 
import numpy as np
import yaml
from pathlib import Path
from argparse import ArgumentParser

"""
Workflow: 
- Filter the states 
- For each state sample X number of personas, seed (X and seed chosen by the user)
    - Sampling probability determined by the common weight 
    - Sample with replacement 
- Keep all of the columns for further analysis 
- Save each state in a separate <State>.parquet file
"""
DEFAULT_DATA_PATH = "data/cleaned/cleaned_CES_data.parquet"
SENATE_STATES_2026 = {
    1: "Alabama",
    2: "Alaska",
    5: "Arkansas",
    8: "Colorado",
    10: "Delaware",
    12: "Florida",
    13: "Georgia",
    16: "Idaho",
    17: "Illinois",
    19: "Iowa",
    20: "Kansas",
    21: "Kentucky",
    22: "Louisiana",
    23: "Maine",
    25: "Massachusetts",
    26: "Michigan",
    27: "Minnesota",
    28: "Mississippi",
    30: "Montana",
    31: "Nebraska",
    33: "New Hampshire",
    34: "New Jersey",
    35: "New Mexico",
    37: "North Carolina",
    39: "Ohio",
    40: "Oklahoma",
    41: "Oregon",
    44: "Rhode Island",
    45: "South Carolina",
    46: "South Dakota",
    47: "Tennessee",
    48: "Texas",
    51: "Virginia",
    54: "West Virginia",
    56: "Wyoming",
}


def args_parser(): 
    parser = ArgumentParser()
    parser.add_argument("--data-path", help= "Input path", 
                         type=str, default=DEFAULT_DATA_PATH)
    parser.add_argument("--seed", help="Set seed for the persona drawing", 
                        type = int, default=42)
    parser.add_argument("--samples", help="Choose number of samples in persona draws", 
                            type = int, default=100)
    parser.add_argument("--run-name", help="Naming convention for output file", 
                                type = str, required=True)
    return parser.parse_args()

def create_personas() -> None:
    args = args_parser()
    rng = np.random.default_rng(args.seed)
    
    df = pl.scan_parquet(Path(args.data_path)
                        ).filter(pl.col("inputstate").is_in(list(SENATE_STATES_2026)))

    output_dir = Path(f"data/personas/{args.run_name}")
    output_dir.mkdir(parents=True, exist_ok =True)

    persona_config = {
        "run_name": args.run_name, 
        "seed": args.seed, 
        "samples": args.samples, 
        "data_path": str(args.data_path)
    }
    for code, state in SENATE_STATES_2026.items(): 
        
        state_df = df.filter(pl.col('inputstate') == code).collect()
        weights = state_df['commonweight'].to_numpy()

        probabilities = weights / weights.sum()

        indices = rng.choice(
            len(state_df), 
            size = args.samples, 
            replace = True, 
            p=probabilities
        )

        state_results = { 
            "population": state_df.shape[0],
            "proportion_sampled": round(args.samples/state_df.shape[0], ndigits=3)
        }
        persona_config[state] = state_results

        personas = state_df[indices]
        personas.write_parquet(output_dir / f"{state}.parquet")
        print(f"Personas created for {state}. {args.samples}/{state_df.shape[0]} (samples/total respondants)")

    with open(output_dir / "persona_config.yaml", "w") as file: 
        yaml.safe_dump(persona_config, file)
    print("Persona config saved")

if __name__ == "__main__": 
    create_personas()
