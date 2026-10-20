"""Query exact retained recording credits and credited-artist context without fitting."""

import argparse
import hashlib
import json
import resource
import signal
from pathlib import Path

MAX_DATABASE_BYTES = 100_000_000
MAX_OUTPUT_BYTES = 2_000_000


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """Require an external database pin and bound a read-only ordinary query."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.serving.public.recording_navigation_store import (  # noqa: PLC0415
        PublicRecordingNavigationStore,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--database-sha256", required=True)
    parser.add_argument("--recording-mbid", required=True)
    parser.add_argument("--genre-limit", type=int, default=10)
    parser.add_argument("--related-limit", type=int, default=5)
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_DATABASE_BYTES:
        raise ValueError("database must be a bounded regular SQLite file")
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("pinned query requires a standalone SQLite database without sidecars")
    if _digest(path) != args.database_sha256:
        raise ValueError("database differs from externally supplied pin")
    result = PublicRecordingNavigationStore(path, immutable=True)._recording_context_sync(  # noqa: SLF001 -- Bounded synchronous CLI entry point.
        args.recording_mbid,
        args.genre_limit,
        args.related_limit,
    )
    payload = json.dumps(result.model_dump(mode="json"), sort_keys=True).encode()
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("recording context exceeds 2 MB output cap")
    if _digest(path) != args.database_sha256:
        raise ValueError("database changed during query")
    print(payload.decode())  # noqa: T201 -- Explicit query result, no file publication.


if __name__ == "__main__":
    main()
