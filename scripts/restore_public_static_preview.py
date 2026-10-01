"""Replay the currently served public OpenNoise static export into .cache."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from opennoise.deployment.public_preview_replay import replay_public_static_preview

_MANIFEST_URL = "https://opennoise.horv.co/opennoise-static-manifest.json"
_LOG = logging.getLogger(__name__)


def main() -> None:
    """Run the bounded public replay command."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-url", default=_MANIFEST_URL)
    parser.add_argument("--output-dir", type=Path, default=Path(".cache/public-static-replay"))
    args = parser.parse_args()
    receipt = replay_public_static_preview(args.manifest_url, args.output_dir)
    _LOG.info("Restored public static preview to %s", args.output_dir.resolve())
    _LOG.info("Manifest logical SHA-256: %s", receipt["manifest_output_sha256"])


if __name__ == "__main__":
    main()
