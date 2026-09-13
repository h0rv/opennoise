"""Launch the loopback-only local MusicBrainz discovery panel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.run_dev import resolve_production_paths


def main() -> int:
    """Start the normal dev app with completed local research inputs enabled."""
    root = Path.cwd()
    production = resolve_production_paths(root)
    inputs = {
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_EVIDENCE_DATABASE": root
        / ".cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite",
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_EVIDENCE_ARTIFACT": root
        / ".cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json",
        "OPENNOISE_LOCAL_RESEARCH_SEED_RECONCILIATION": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
        "OPENNOISE_LOCAL_RESEARCH_ADAPTER_REPORT": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json",
        "OPENNOISE_LOCAL_RESEARCH_REVIEWED_ALIAS_CONTEXT_ARTIFACT": root
        / ".cache/reviewed-alias-context-v1/artifact-v1.json",
        "OPENNOISE_LOCAL_RESEARCH_REVIEWED_ALIAS_CONTEXT_RECEIPT": root
        / ".cache/reviewed-alias-combined-model-v1/receipt.json",
        "OPENNOISE_LOCAL_RESEARCH_REVIEWED_ALIAS_PEER_INDEX": root
        / ".cache/reviewed-alias-combined-model-v1/peer-similarity-local-research.sqlite",
        "OPENNOISE_LOCAL_RESEARCH_PEER_LAYOUT": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/peer-community-layout-v1.json",
        "OPENNOISE_LOCAL_RESEARCH_MAP_PEER_INDEX": root
        / ".cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite",
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_METADATA_DATABASE": root
        / ".cache/musicbrainz-release-group-artist-metadata-v1/metadata.sqlite",
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_METADATA_ARTIFACT": root
        / ".cache/musicbrainz-release-group-artist-metadata-v1/artifact.json",
    }
    reverse_lookup = {
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_REVERSE_LOOKUP_DATABASE": root
        / ".cache/musicbrainz-release-group-evidence-candidate-v1/artist-reverse-lookup.sqlite",
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_REVERSE_LOOKUP_ARTIFACT": root
        / (
            ".cache/musicbrainz-release-group-evidence-candidate-v1/"
            "artist-reverse-lookup-artifact.json"
        ),
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        sys.stderr.write("Local research inputs are unavailable:\n" + "\n".join(missing) + "\n")
        return 2
    sidecar_present = tuple(path.is_file() for path in reverse_lookup.values())
    if any(sidecar_present) and not all(sidecar_present):
        sys.stderr.write("Local artist reverse lookup requires both database and artifact files.\n")
        return 2
    environment = os.environ | {
        # Local research has its own sealed map input; it must remain usable
        # when a public release pair is intentionally absent.
        "OPENNOISE_DATABASE_PATH": str(
            production.database if production else root / ".cache/local-research-dev.sqlite"
        ),
        "OPENNOISE_DATABASE_READ_ONLY": "true" if production else "false",
        **(
            {"OPENNOISE_PRODUCTION_MAP_PATH": str(production.map_artifact)}
            if production
            else {}
        ),
        "HOST": "127.0.0.1",
        "PORT": os.environ.get("PORT", "3002"),
        "OPENNOISE_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED": "false",
        "OPENNOISE_LOCAL_RESEARCH_REVIEWED_ALIAS_CONTEXT_ENABLED": "false",
        **{key: str(value) for key, value in inputs.items()},
        **(
            {key: str(value) for key, value in reverse_lookup.items()}
            if all(sidecar_present)
            else {}
        ),
    }
    return subprocess.run(
        [sys.executable, "-m", "opennoise.serving.cli", "serve"], check=False, env=environment
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
