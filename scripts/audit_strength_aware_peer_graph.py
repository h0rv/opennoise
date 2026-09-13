"""Write a replayable local-only strength-aware peer audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.peers.audit.strength_aware_peer_audit import build_strength_aware_peer_audit


def main() -> int:
    """Audit one strength-aware direct/support peer graph."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(arguments.output)
    artifact = build_strength_aware_peer_audit(arguments.direct, arguments.support)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
