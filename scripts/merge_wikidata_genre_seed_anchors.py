"""Write a high-confidence, anchor-only merge projection from a resolver batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.wikidata.resolver import (
    merge_wikidata_public_anchors,
    write_wikidata_public_anchor_merge,
)
from opennoise.storage import LocalObjectStore, ObjectKey


def main() -> int:
    """Build and publish a no-membership public anchor merge projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        artifact = merge_wikidata_public_anchors(arguments.resolution_artifact)
        byte_sha, byte_size = write_wikidata_public_anchor_merge(artifact, arguments.output)
        object_write = LocalObjectStore(arguments.object_store).push(
            arguments.output,
            ObjectKey(value=f"wikidata-public-anchor-merge/{byte_sha}/{arguments.output.name}"),
        )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Wikidata public anchor merge failed: {error}\n")
        return 2
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": artifact.output_sha256,
                "anchor_count": artifact.anchor_count,
                "artist_membership_count": artifact.artist_membership_count,
                "byte_sha256": byte_sha,
                "byte_size": byte_size,
                "object_write": object_write.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
