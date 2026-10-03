"""Build or replay the separately named full retained open-input reconstruction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.pipeline.full_input_context import FullInputSources
from opennoise.pipeline.full_input_foundation import (
    assemble_full_input_foundation,
    build_full_input_foundation,
    seal_full_input_foundation,
    validate_full_input_foundation,
)


def main() -> None:
    """Keep this profile independent of sealed legacy build/deploy inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "assemble", "seal", "validate"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entity-pack", type=Path)
    parser.add_argument("--identity-base", type=Path)
    parser.add_argument("--source-base", type=Path)
    parser.add_argument("--source-proof", type=Path)
    parser.add_argument("--research-base", type=Path)
    for name in (
        "listening-pack",
        "fma-source",
        "fma-projection",
        "fma-bridge",
        "fma-static",
        "fma-listening-pack",
        "genre-context-pack",
        "fma-map",
        "fma-memberships",
        "artist-source-completion",
    ):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    inputs = FullInputSources(
        args.entity_pack,
        args.listening_pack,
        args.fma_source,
        args.fma_projection,
        args.fma_bridge,
        args.fma_static,
        args.fma_listening_pack,
        args.genre_context_pack,
        args.fma_map,
        args.fma_memberships,
        args.artist_source_completion,
    )
    if args.command == "build":
        result = build_full_input_foundation(args.root, args.output, inputs, args.identity_base)
    elif args.command == "assemble":
        if args.source_base is None or args.source_proof is None:
            parser.error("assemble requires --source-base and --source-proof")
        result = assemble_full_input_foundation(
            args.root, args.output, inputs, args.source_base, args.source_proof, args.research_base
        )
    elif args.command == "seal":
        result = seal_full_input_foundation(args.root, args.output, inputs)
    else:
        result = validate_full_input_foundation(args.root, args.output, inputs)
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
