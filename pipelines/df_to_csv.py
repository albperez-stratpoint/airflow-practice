from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_sample_df_to_csv(output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(
        [
            {"id": 1, "name": "alice", "score": 10},
            {"id": 2, "name": "bob", "score": 20},
            {"id": 3, "name": "carol", "score": 30},
        ]
    )

    df.to_csv(path, index=False)
    return str(path)
