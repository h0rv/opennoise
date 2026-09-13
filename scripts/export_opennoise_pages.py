"""Stage a sealed semantic production map for the reviewed OpenNoise static export."""

from __future__ import annotations

import argparse
from pathlib import Path

from musix.deployment.opennoise_pages import OpenNoisePagesExportInputs, export_opennoise_pages


def main() -> int:
    """Require explicit source and empty destination paths for static staging."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-map", type=Path, required=True)
    parser.add_argument("--open-construction-v2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = export_opennoise_pages(
        OpenNoisePagesExportInputs(
            production_map_path=arguments.production_map,
            open_construction_v2_path=arguments.open_construction_v2,
            output_directory=arguments.output,
        )
    )
    print(manifest.model_dump_json(indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
