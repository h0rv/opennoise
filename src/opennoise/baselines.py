import csv
import json
from pathlib import Path


def baselines() -> None:
    with Path("experiments/results.tsv").open() as stream:
        ledger = list(csv.DictReader(stream, delimiter="\t"))

    def metrics(run: str, change: str):
        rows = [row for row in ledger if row["config"] == run and row["change"] == change]
        if len(rows) != 1:
            raise ValueError(f"expected one ledger row for {run}/{change}, found {len(rows)}")
        return json.loads(rows[0]["metrics"])

    en = metrics("e234d830601e/fine_k20", "m2")
    wd = metrics("672c8724cb3f", "generalization")["slices"]["sealed"]["m2"]
    neighbors = metrics("6bde97e2d5c8", "discogs_styles_references")
    rows = [("Check", "Graph", "Slice size", "Score")]
    for check, result, size_key in (
        ("Hidden Every Noise genres found as a cluster (M2)", en, "heldout_genres"),
        ("Sealed Wikidata genres found as a cluster (M2)", wd, "genres"),
    ):
        size = result[size_key]
        score = result["genre_match"]
        found = result["matched_genres"] if "matched_genres" in result else round(score * size)
        rows.append(
            (check, "Listening (TF-IDF)", f"{size:,} genres", f"{found}/{size} = {score:.1%}")
        )
    for method, graph in (("tfidf", "TF-IDF"), ("discogs_0.1", "Discogs styles (0.1)")):
        for reference, label in (("enao", "hidden Every Noise"), ("sealed", "sealed Wikidata")):
            result = neighbors[method]["references"][reference]
            rows.append(
                (
                    f"Top-10 similar artists sharing a {label} genre",
                    graph,
                    f"{result['artists']:,} artists",
                    f"{result['agreement@10']:.2%}",
                )
            )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    for row in rows:
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)))
