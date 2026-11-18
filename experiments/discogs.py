import argparse
import json
import time
import tomllib
from pathlib import Path

import polars as pl

from opennoise.generalization import evaluate
from opennoise.genres import heldout_genres
from opennoise.tags import genre_agreement, log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run
    config = tomllib.loads((run / "config.toml").read_text())
    m2 = tomllib.loads(Path("configs/m2.toml").read_text())
    generalization = tomllib.loads(Path("configs/gen.toml").read_text())
    artists = pl.read_parquet(Path(config["tags"]["base_run"]) / "artists.parquet")
    reference = pl.read_parquet("data/m2/labels.parquet").filter(
        pl.col("genre").is_in(sorted(heldout_genres(m2)))
    )
    results = json.loads((run / "metrics.json").read_text())
    summary = {}
    for method, metrics in results.items():
        if "test" not in metrics:
            continue
        start = time.monotonic()
        edges = run / f"{method}.parquet"
        heldout = genre_agreement(pl.read_parquet(edges), reference, len(artists), config["seed"])
        target = run / method
        target.mkdir(exist_ok=True)
        candidate = generalization | {"m1": generalization["m1"] | {"edges": str(edges)}}
        (target / "config.json").write_text(json.dumps(candidate, indent=2))
        evaluate(candidate, target)
        wikidata = json.loads((target / "metrics.json").read_text())
        summary[method] = {
            "validation": metrics["validation"],
            "test": metrics["test"],
            "enao_heldout": heldout,
            "sealed": wikidata["slices"]["sealed"]["m1"],
            "sealed_independent": wikidata["slices"]["sealed_independent"]["m1"],
            "seconds": time.monotonic() - start,
        }
        log(
            run,
            f"{method}_references",
            summary[method],
            note="validation-selected weight; no tuning",
        )
    (run / "references.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
