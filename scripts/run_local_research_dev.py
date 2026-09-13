"""Launch the loopback-only local MusicBrainz discovery panel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Start the normal dev app with completed local research inputs enabled."""
    root = Path.cwd()
    inputs = {
        "OPENNOISE_LOCAL_RESEARCH_SEED_RECONCILIATION": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
        "OPENNOISE_LOCAL_RESEARCH_PEER_LAYOUT": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json",
        "OPENNOISE_LOCAL_RESEARCH_MAP_PEER_INDEX": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        sys.stderr.write("Local research inputs are unavailable:\n" + "\n".join(missing) + "\n")
        return 2
    sys.stderr.write(
        "Semantic map source: local-research-peer-layout (1,580 placed / 6,291 seeds). "
        "Artist detail is disabled unless explicitly configured.\n"
    )
    environment = os.environ | {
        # Map-only startup intentionally does not open a release database.
        "OPENNOISE_DATABASE_PATH": str(root / ".cache/local-research-dev.sqlite"),
        "OPENNOISE_DATABASE_READ_ONLY": "false",
        "OPENNOISE_MAP_ONLY": "true",
        "OPENNOISE_PRODUCTION_MAP_PATH": "",
        "HOST": "127.0.0.1",
        "PORT": os.environ.get("PORT", "3002"),
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED": "false",
        "OPENNOISE_LOCAL_RESEARCH_REVIEWED_ALIAS_CONTEXT_ENABLED": "false",
        **{key: str(value) for key, value in inputs.items()},
    }
    return subprocess.run(
        [sys.executable, "-m", "opennoise.serving.cli", "serve"], check=False, env=environment
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
