import argparse
import json
import tomllib
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from opennoise import genres, layout
from opennoise.mlhd import weighted_rows


def user_features(lb, mlhd, weight):
    if not np.isfinite(weight) or weight < 0:
        raise ValueError("MLHD weights must be finite and nonnegative")
    rows = [weighted_rows(lb), weighted_rows(mlhd)]
    rows[1].data *= np.float32(np.sqrt(weight))
    return normalize(sparse.vstack(rows, format="csr").T.tocsr())


def run_comparison(source, base, mlhd_run):
    result = json.loads((mlhd_run / "experiment.json").read_text()) if source == "mlhd" else {}
    weight = float(result.get("selected_weight", 0))
    run = Path(f"runs/mlhd-complete-{source}-m2")
    run.mkdir(parents=True, exist_ok=True)
    inputs = run / "input"
    inputs.mkdir(exist_ok=True)
    for filename in ["artists.parquet", "train.npz"]:
        path = inputs / filename
        if not path.exists():
            path.symlink_to((base / filename).resolve())
    graph = mlhd_run / f"weight-{weight:g}.parquet" if weight else base / "tfidf.parquet"
    if not (inputs / "tfidf.parquet").exists():
        (inputs / "tfidf.parquet").symlink_to(graph.resolve())
    m2_text = Path("configs/m2.toml").read_text()
    config = tomllib.loads(m2_text)
    m2_text = m2_text.replace(f'm1 = "{config["m1"]}"', f'm1 = "{inputs}"')
    (run / "m2.toml").write_text(m2_text)
    config["m1"] = str(inputs)
    heldout = sorted(genres.heldout_genres(config))
    (run / "heldout.json").write_text(json.dumps(heldout))
    if len(heldout) != 868:
        raise ValueError("Rebuilt inputs do not reproduce the 868-genre M2 holdout")
    if source == "mlhd":
        original = json.loads(Path("runs/mlhd-complete-baseline-m2/heldout.json").read_text())
        if heldout != original:
            raise ValueError("Baseline and MLHD genre holdouts differ")
    genres.build_genres(config, run)
    genres.evaluate_genres(config, run)
    layout_run = Path(f"runs/mlhd-complete-{source}-layout")
    layout_run.mkdir(exist_ok=True)
    settings = tomllib.loads(Path("configs/layout.toml").read_text())
    settings.update(m2_config=str(run / "m2.toml"), representations=["tfidf"], concat=False)
    if weight and not (layout_run / "tfidf_svd.npy").exists():
        lb = sparse.load_npz(base / "train.npz")
        matrices = [sparse.load_npz(mlhd_run / f"mlhd-{shard}.npz") for shard in "0123456789abcdef"]
        extra = sparse.vstack(matrices).tocsr()
        del matrices
        vectors = user_features(lb, extra, weight)
        del lb, extra
        with threadpool_limits(limits=settings["workers"]):
            vectors = TruncatedSVD(
                n_components=settings["dimensions"], random_state=settings["seed"]
            ).fit_transform(vectors)
        np.save(layout_run / "tfidf_svd.npy", normalize(vectors).astype(np.float32))
    (layout_run / "experiment.json").write_text(
        json.dumps(
            {
                "source": source,
                "weight": weight,
                "settings": settings,
                "representation": "TF-IDF user features matching similarity graph",
            },
            indent=2,
        )
    )
    layout.layout(settings, layout_run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["baseline", "mlhd"])
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--base", type=Path, default=Path("runs/1f242e47ed38"))
    parser.add_argument("--mlhd-run", type=Path, default=Path("runs/mlhd-complete"))
    args = parser.parse_args()
    if not args.enable:
        parser.error("MLHD is disabled by default; pass --enable to opt in")
    run_comparison(args.source, args.base, args.mlhd_run)


if __name__ == "__main__":
    main()
