"""Build, gate, and immutable-store an Open 6,291 graph v2 from an expansion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.serving.open.open_construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    publish_open_construction_graph_v2,
)
from musix.storage import LocalObjectStore


def main() -> None:
    """Require explicit retained inputs; never discover an ignored local cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-expansion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-legacy-seed-count", type=int, default=6291)
    arguments = parser.parse_args()
    artifact = build_open_construction_graph_v2(
        arguments.taxonomy_expansion,
        config=OpenConstructionGraphV2Config(
            expected_legacy_seed_count=arguments.expected_legacy_seed_count,
        ),
    )
    receipt, _ = publish_open_construction_graph_v2(
        artifact,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
