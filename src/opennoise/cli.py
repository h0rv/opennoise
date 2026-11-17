import argparse
import hashlib
import json
import time
import tomllib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="on")
    parser.add_argument("stage", choices=["ingest", "build", "eval"])
    parser.add_argument("config", nargs="?", default="configs/m1.toml")
    args = parser.parse_args()
    config_bytes = Path(args.config).read_bytes()
    config = tomllib.loads(config_bytes.decode())
    digest = hashlib.sha256(config_bytes + Path("sources.toml").read_bytes()).hexdigest()[:12]
    run = Path("runs") / digest
    run.mkdir(parents=True, exist_ok=True)
    (run / "config.toml").write_bytes(config_bytes)
    start = time.monotonic()
    if config.get("milestone") == "m2":
        from opennoise.genres import build_genres, evaluate_genres
        from opennoise.reference import ingest_reference

        if args.stage == "ingest":
            ingest_reference(config)
        elif args.stage == "build":
            build_genres(config, run)
        else:
            evaluate_genres(config, run)
    elif args.stage == "ingest":
        from opennoise.ingest import ingest

        ingest()
    elif args.stage == "build":
        from opennoise.graph import build

        build(config, run)
    else:
        from opennoise.evaluate import evaluate

        evaluate(config, run)
    elapsed = time.monotonic() - start
    print(json.dumps({"run": str(run), "stage": args.stage, "seconds": elapsed}))
