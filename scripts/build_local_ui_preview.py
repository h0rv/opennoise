"""Build the current UI against a verified public static replay, without publication."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from opennoise.deployment.public_preview_replay import build_local_ui_preview

_LOG = logging.getLogger(__name__)


def main() -> None:
    """Build a new, receipt-bound local UI preview from retained public metadata."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path, default=Path(".cache/public-static-replay"))
    parser.add_argument("--output-dir", type=Path, default=Path(".cache/ui-preview"))
    arguments = parser.parse_args()
    receipt = build_local_ui_preview(arguments.replay_dir, arguments.output_dir)
    _LOG.info("Built local UI preview: %s (%s)", arguments.output_dir, receipt["output_sha256"])


if __name__ == "__main__":
    main()
