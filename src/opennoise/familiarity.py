import argparse
import json
import tomllib
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl

from opennoise.genre_order import everynoise
from opennoise.metrics import sealed
from opennoise.names import canonical, key
from opennoise.tags import log


def priority(score, listeners, alpha):
    return score / max(listeners or 1, 1) ** alpha


def evaluate(root, references, alphas=(0, 0.025, 0.05, 0.075, 0.1, 0.2)):
    labels = {}
    for name, frame in references.items():
        labels[name] = defaultdict(set)
        for artist, genre in frame.select("artist_mbid", "genre").unique().iter_rows():
            labels[name][artist].add(key(canonical(genre)))
    artists = set().union(*(set(ref) for ref in labels.values()))
    values = {a: {name: [] for name in labels} for a in alphas}
    listeners = {a: [] for a in alphas}
    for artist in sorted(artists):
        path = root / "artists" / f"{artist}.json"
        if not path.exists():
            continue
        similar = json.loads(path.read_text())["similar"] or []
        for alpha in alphas:
            top = sorted(
                similar,
                key=lambda m: (
                    -priority(m["score"], m["artist"]["listeners"], alpha),
                    m["artist"]["id"],
                ),
            )[:10]
            listeners[alpha].extend(max(m["artist"]["listeners"] or 1, 1) for m in top)
            for name, reference in labels.items():
                if artist not in reference or (name == "wikidata" and not sealed(artist)):
                    continue
                eligible = [m["artist"]["id"] for m in top if m["artist"]["id"] in reference]
                if eligible:
                    values[alpha][name].append(
                        np.mean(
                            [bool(reference[artist] & reference[neighbor]) for neighbor in eligible]
                        )
                    )
    return {
        str(a): {
            "median_listeners": float(np.median(listeners[a])) if listeners[a] else None,
            **{
                name: {"agreement": float(np.mean(v)) if v else None, "artists": len(v)}
                for name, v in values[a].items()
            },
        }
        for a in alphas
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    results = evaluate(
        args.release,
        {
            "wikidata": pl.read_parquet(args.reference / "wikidata" / "wikidata.parquet"),
            "everynoise": everynoise(
                args.reference, args.release, tomllib.loads(Path("configs/m2.toml").read_text())
            ),
        },
    )
    for alpha, result in results.items():
        log(
            args.release,
            f"familiarity/{alpha}",
            result,
            kept=alpha == "0.1",
            note="score/listeners^alpha; null=1; sealed Wikidata focal artists; labeled neighbors",
        )
