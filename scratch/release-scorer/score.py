import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from scipy.spatial.distance import cdist
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits


def nearest(points, metric="euclidean"):
    points = np.asarray(points)
    if points.ndim != 2 or len(points) < 11 or not np.isfinite(points).all():
        raise ValueError("Expected at least 11 finite vectors in a two-dimensional array")
    chunks = []
    for start in range(0, len(points), 128):
        distances = cdist(points[start : start + 128], points, metric)
        distances[np.arange(len(distances)), np.arange(start, start + len(distances))] = np.inf
        chunks.append(np.argsort(distances, axis=1, kind="stable")[:, :10])
    return np.concatenate(chunks)


def shared(first, second):
    return np.array([len(set(a) & set(b)) / 10 for a, b in zip(first, second, strict=True)])


def spread(points):
    unit = (points - points.min(0)) / np.maximum(np.ptp(points, axis=0), 1e-12)
    histogram = np.histogram2d(unit[:, 0], unit[:, 1], bins=10, range=[[0, 1], [0, 1]])[0]
    return {
        "cells": int((histogram > 0).sum()),
        "largest_cell": float(histogram.max() / len(points)),
    }


class Scorer:
    def __init__(self, references):
        pool = json.loads((references / "pool.json").read_text())
        self.ids = [row["id"] for row in pool]
        self.names = [row["original_name"] for row in pool]
        heldout_ids = set((references / "heldout-ids.txt").read_text().splitlines())
        if len(self.ids) != 4140 or len(set(self.ids)) != 4140:
            raise ValueError("Expected the frozen 4,140 unique stable IDs")
        if len(heldout_ids) != 815 or not heldout_ids <= set(self.ids):
            raise ValueError("Expected 815 held-out IDs within the frozen pool")
        self.heldout = np.array([identifier in heldout_ids for identifier in self.ids])
        with np.load(references / "vectors.npz", allow_pickle=False) as data:
            vectors = data["vectors"]
        if len(vectors) != len(self.ids):
            raise ValueError("Vector rows must follow the frozen pool order")
        self.raw = nearest(vectors, "cosine")
        enao = pl.DataFrame({"genre": self.names}).join(
            pl.read_parquet(references / "map.parquet"), on="genre", maintain_order="left"
        )
        self.enao = nearest(enao.select("x", "y").to_numpy())
        members = pl.read_parquet(references / "members.parquet")
        reference = pl.read_parquet(references / "wikidata.parquet")
        joined = members.join(reference.select("artist_mbid", "genre_qid"), on="artist_mbid")
        qi = {q: i for i, q in enumerate(sorted(set(joined["genre_qid"])))}
        gi = {name: i for i, name in enumerate(self.names)}
        counts = (
            joined.filter(pl.col("genre").is_in(self.names)).group_by("genre", "genre_qid").len()
        )
        self.wd = normalize(
            sparse.csr_matrix(
                (
                    counts["len"].to_numpy().astype(float),
                    ([gi[g] for g in counts["genre"]], [qi[q] for q in counts["genre_qid"]]),
                ),
                shape=(len(gi), len(qi)),
            )
        )
        self.wrandom = (np.asarray(self.wd @ np.asarray(self.wd.sum(0)).ravel()).ravel() - 1) / (
            len(gi) - 1
        )

    def score(self, points):
        points = np.asarray(points)
        if points.shape != (len(self.ids), 2):
            raise ValueError("Release coordinates must have shape (4140, 2)")
        knn = nearest(points)
        wikidata = np.mean(
            [np.asarray(self.wd.multiply(self.wd[knn[:, i]]).sum(1)).ravel() for i in range(10)],
            axis=0,
        )
        overlap = shared(knn, self.enao)
        retention = shared(knn, self.raw)
        result = dict(
            wikidata=float(wikidata.mean()),
            enao=float(overlap.mean()),
            retention=float(retention.mean()),
            random_wikidata=float(self.wrandom.mean()),
            random_overlap=10 / (len(points) - 1),
            **spread(points),
        )
        for name, mask in [("development", ~self.heldout), ("heldout", self.heldout)]:
            result[name] = {
                "n": int(mask.sum()),
                "wikidata": float(wikidata[mask].mean()),
                "enao": float(overlap[mask].mean()),
                "retention": float(retention[mask].mean()),
                "random_wikidata": float(self.wrandom[mask].mean()),
            }
        return result

    def score_release(self, release):
        catalog = {row["id"]: row for row in json.loads((release / "genres.json").read_text())}
        missing = set(self.ids) - catalog.keys()
        if missing:
            raise ValueError(f"Release is missing {len(missing)} frozen IDs: {sorted(missing)[:5]}")
        points = np.array(
            [
                [catalog[identifier]["positions"]["axes"][axis] for axis in ("x", "y")]
                for identifier in self.ids
            ],
            dtype=float,
        )
        manifest = json.loads((release / "manifest.json").read_text())
        return {"release_id": manifest["release_id"], "pool": len(self.ids), **self.score(points)}


def main():
    parser = argparse.ArgumentParser(description="Score exported axes on the frozen stable-ID pool")
    parser.add_argument("releases", type=Path, nargs="+", help="Extracted release directories")
    parser.add_argument("--references", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        scorer = Scorer(args.references)
        for release in args.releases:
            print(json.dumps(scorer.score_release(release)), flush=True)


if __name__ == "__main__":
    main()
