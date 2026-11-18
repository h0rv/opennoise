import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from opennoise.tags import log


def run_config(path, content, stages):
    path.write_text(content)
    digest = hashlib.sha256(content.encode() + Path("sources.toml").read_bytes()).hexdigest()[:12]
    run = Path("runs") / digest
    for stage in stages:
        if stage == "eval" and (run / "metrics.json").exists():
            continue
        subprocess.run(["on", stage, str(path)], check=True)
    return run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["baseline", "0.1", "0.3", "1.0"])
    parser.add_argument("--types", nargs="+")
    args = parser.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("POLARS_MAX_THREADS", "4")
    root = Path("runs/mb-relations")
    root.mkdir(parents=True, exist_ok=True)
    label = args.variant + ("-subset" if args.types else "")
    if args.variant == "baseline":
        if args.types:
            parser.error("baseline cannot filter relations")
        content = Path("configs/m2.toml").read_text()
    else:
        content = Path("configs/m2-relations.toml").read_text()
        content = content.replace("weight = 0.1", f"weight = {args.variant}")
        if args.types:
            content = content.replace(
                "[relations]", "[relations]\ntypes = " + json.dumps(args.types)
            )
    m2 = run_config(root / f"{label}.toml", content, ["build", "eval"])
    memberships = m2 / "fine_k20/memberships.parquet"
    genres = m2 / "fine_k20/genres.parquet"
    generalization = (
        'milestone = "gen"\nseed = 42\nreference = "data/gen"\n'
        'crosswalk = "data/m2/crosswalk.parquet"\n\n'
        '[m1]\nartists = "runs/1f242e47ed38/artists.parquet"\n'
        'edges = "runs/1f242e47ed38/tfidf.parquet"\n\n'
        f'[m2]\nmemberships = "{memberships}"\ngenres = "{genres}"\n'
    )
    gen = run_config(root / f"{label}-gen.toml", generalization, ["eval"])
    m2_metrics = json.loads((m2 / "fine_k20/metrics.json").read_text())
    gen_metrics = json.loads((gen / "metrics.json").read_text())
    result = {
        "variant": label,
        "weight": 0 if args.variant == "baseline" else float(args.variant),
        "types": args.types,
        "m2_run": str(m2),
        "gen_run": str(gen),
        "m2": m2_metrics,
        "sealed": gen_metrics["slices"]["sealed"]["m2"],
        "sealed_independent": gen_metrics["slices"]["sealed_independent"]["m2"],
        "reference_sha256": gen_metrics["reference_sha256"],
    }
    (root / f"{label}.json").write_text(json.dumps(result, indent=2))
    results = [json.loads(path.read_text()) for path in sorted(root.glob("*.json"))]
    best = max(results, key=lambda row: (row["m2"]["genre_match"], row["m2"]["member_ap"]))
    for row in results:
        log(
            Path(row["m2_run"]),
            "mb_relations_comparison",
            row,
            kept=row["variant"] == best["variant"],
            note="selection by Every Noise genre_match then member_ap; Wikidata is diagnostic",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
