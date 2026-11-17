import argparse
import hashlib
import json
import time
import tomllib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="on")
    parser.add_argument("stage", choices=["ingest", "build", "eval", "export", "layout"])
    parser.add_argument("config", nargs="?")
    args = parser.parse_args()
    if args.config is None:
        args.config = "configs/layout.toml" if args.stage == "layout" else "configs/m1.toml"
    config_bytes = Path(args.config).read_bytes()
    config = tomllib.loads(config_bytes.decode())
    if args.stage == "export" and config.get("milestone") not in {"m2b", "m2c", "m2d"}:
        parser.error("export requires an M2b, M2c or M2d config")
    if config.get("milestone") == "m2d" and args.stage != "export":
        parser.error("M2d only adapts existing artifacts; use export")
    inputs = config_bytes + Path("sources.toml").read_bytes()
    if args.stage == "layout":
        inputs += Path(config["m2_config"]).read_bytes()
    digest = hashlib.sha256(inputs).hexdigest()[:12]
    run = Path("runs") / digest
    run.mkdir(parents=True, exist_ok=True)
    (run / "config.toml").write_bytes(config_bytes)
    start = time.monotonic()
    if config.get("milestone") == "m2d":
        from opennoise.catalog import execute

        execute(args.stage, config, run)
    elif config.get("milestone") == "m2c":
        from opennoise.wikidata import execute

        execute(args.stage, config, run)
    elif config.get("milestone") == "m2b":
        from opennoise.naming import execute

        execute(args.stage, config, run)
    elif config.get("milestone") == "m2":
        from opennoise.genres import build_genres, evaluate_genres
        from opennoise.reference import ingest_reference

        if args.stage == "ingest":
            ingest_reference(config)
        elif args.stage == "build":
            build_genres(config, run)
        else:
            evaluate_genres(config, run)
    elif "tags" in config:
        from opennoise import tags

        tags.execute(args.stage, config, run)
    elif args.stage == "ingest":
        from opennoise.ingest import ingest

        ingest()
    elif args.stage == "build":
        from opennoise.graph import build

        build(config, run)
    elif args.stage == "eval":
        from opennoise.evaluate import evaluate

        evaluate(config, run)
    else:
        from opennoise.layout import layout

        layout(config, run)
    elapsed = time.monotonic() - start
    print(json.dumps({"run": str(run), "stage": args.stage, "seconds": elapsed}))
