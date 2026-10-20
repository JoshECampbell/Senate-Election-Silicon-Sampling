"""
Workflow: 
1. Read in the config for the ces codes
2. Create 100 personas from a single state (Wyoming) that include all of the columns in the CES codes 
3. Make the common weight a random number between 0.1 and 3, codes should be 4 digit identifiers  
4. Have random labels for the rest of the columns (int or float)
5. Dump the data in data/simulated/personas
"""
import polars as pl
import numpy as np
import yaml
from pathlib import Path


def sim_persona_data():
    with open("config/ces_codes/ces25_value_labels.yaml", "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    rng = np.random.default_rng(42)
    num_personas = 100
    data = {}

    for column, details in config["variables"].items():
        if column == "caseid":
            data[column] = rng.choice(np.arange(1000, 10000), size=num_personas, replace=False)
        elif column == "commonweight":
            data[column] = rng.uniform(0.1, 3, size=num_personas)
        elif column == "inputstate":
            data[column] = np.full(num_personas, 56)
        elif column == "birthyr":
            data[column] = rng.integers(1940, 2008, size=num_personas)
        else:
            data[column] = rng.choice(list(details["codes"]), size=num_personas)

    df = pl.DataFrame(data)
    output_dir = Path("data/simulated/personas")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "Wyoming.parquet"
    df.write_parquet(output_path)

    print(f"Simulated personas saved to: {output_path}, Shape = {df.shape}")


if __name__ == "__main__":
    sim_persona_data()
