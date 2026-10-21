"""Opt-in local native melody alignment with a bounded per-window pitch offset."""

import argparse
import hashlib
import os
import resource
import signal
import tempfile
from pathlib import Path

MAX_JSON = 1_000_000


def _write(output: Path, payload: bytes) -> None:
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("result destination must be fresh without symlinks")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    try:
        os.link(temporary, output)
    finally:
        temporary.unlink()


def main() -> None:
    """Query an unchanged externally pinned source pack, without fitting or fetching."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    from opennoise.ml import (  # noqa: PLC0415 -- Apply process bounds before numeric imports.
        medley_melody as native,
    )
    from opennoise.ml import (  # noqa: PLC0415 -- Same bounded lazy numerical import.
        transposed_melody as melody,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--query", type=Path, required=True)
    parser.add_argument("--query-sha256", required=True)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is not None and (
        args.output.resolve().is_relative_to(args.source.resolve())
        or args.output.resolve() == args.query.resolve()
    ):
        raise ValueError("result output overlaps inputs")
    request = native._json(native.read_pinned(args.query, args.query_sha256, MAX_JSON))  # noqa: SLF001 -- Reuse original strict JSON boundary.
    source = native.load_source(args.source, args.source_sha256)
    result = melody.search_contour(source, request, limit=args.limit)
    payload = native.encoded(result)
    if len(payload) > MAX_JSON:
        raise ValueError("bounded pitch-offset result exceeds 1 MB cap")
    if args.output is not None:
        _write(args.output, payload)
        payload = native.encoded({"result_sha256": hashlib.sha256(payload).hexdigest()})
    print(payload.decode().rstrip())  # noqa: T201 -- Explicit local research result only.


if __name__ == "__main__":
    main()
