"""Run or verify the fixed offline feature-bank and nonlinear backend stages."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.pipeline.fma_backend import prepare, run, verify


def main() -> None:
    """Use explicit paths and external plan/checkpoint pins."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "verify"))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--roles", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--max-stages", type=int, choices=range(1, 44), default=43)
    args = parser.parse_args()
    if args.stage == "prepare":
        if args.roles is None:
            parser.error("prepare requires --roles JSON with relative input role paths")
        result = {
            "plan_sha256": prepare(
                args.inputs, args.repo, args.output, json.loads(args.roles.read_text())
            )
        }
    else:
        if args.plan_sha256 is None:
            parser.error("run and verify require --plan-sha256")
        if args.stage == "verify":
            result = verify(args.output, args.inputs, args.plan_sha256, args.checkpoint_sha256)
        else:
            result = run(
                args.output,
                args.inputs,
                args.repo,
                args.plan_sha256,
                args.checkpoint_sha256,
                max_stages=args.max_stages,
            )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
