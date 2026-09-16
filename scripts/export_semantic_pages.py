"""Export the canonical semantic atlas as a static Cloudflare Pages directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from opennoise.deployment.semantic_pages import SemanticPagesExportInputs, export_semantic_pages


def main() -> int:
    """Export one verified semantic atlas into an empty static directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-layout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--discovery-database",
        type=Path,
        default=Path(os.environ.get("OPENNOISE_DISCOVERY_DATABASE", "data/public.sqlite")),
    )
    arguments = parser.parse_args()
    print(  # noqa: T201
        export_semantic_pages(
            SemanticPagesExportInputs(
                arguments.semantic_layout,
                arguments.output,
                arguments.discovery_database,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
