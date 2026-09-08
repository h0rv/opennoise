"""Write the local-only independently corroborated peer-core audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from musix.strength_aware_peer_audit import build_corroborated_peer_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(build_corroborated_peer_audit(args.direct, args.support).model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
