"""Export one explicit local-only MusicBrainz credit artist-detail JSON payload."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.deployment.musicbrainz_credit_artist_detail_local import (
    export_local_musicbrainz_credit_artist_detail_payload,
)


def main() -> int:
    """Export below a caller-selected ``.cache`` root; this command never chooses ``dist``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credit-metadata", required=True, type=Path)
    parser.add_argument("--static-discovery", required=True, type=Path)
    parser.add_argument("--static-artist-id", required=True)
    parser.add_argument("--local-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    _, digest = export_local_musicbrainz_credit_artist_detail_payload(
        credit_metadata=arguments.credit_metadata,
        static_discovery=arguments.static_discovery,
        static_artist_id=arguments.static_artist_id,
        local_root=arguments.local_root,
        output=arguments.output,
    )
    print(digest)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
