"""Build a local research source pack or align caller-supplied native f0 coordinates."""

import argparse
import hashlib
import os
import resource
import signal
import tempfile
from pathlib import Path

MAX_JSON = 1_000_000


def _publish(output: Path, payload: bytes) -> None:
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("result destination must be fresh")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    try:
        os.link(temporary, output)
    finally:
        temporary.unlink()


def main() -> None:
    """Bound each local invocation; never acquire sources or invoke model fitting."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    from opennoise.ml import (  # noqa: PLC0415 -- Resource limits precede NumPy.
        medley_melody as melody,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    build = commands.add_parser("build")
    build.add_argument("--raw", type=Path, required=True)
    for name in ("pilot", "preflight", "census"):
        build.add_argument("--" + name, type=Path, required=True)
        build.add_argument("--" + name + "-sha256", required=True)
    build.add_argument("--output", type=Path, required=True)
    query = commands.add_parser("query")
    query.add_argument("--source", type=Path, required=True)
    query.add_argument("--source-sha256", required=True)
    query.add_argument("--query", type=Path, required=True)
    query.add_argument("--query-sha256", required=True)
    query.add_argument("--limit", type=int, default=24)
    query.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        pin = melody.build_source(
            args.raw,
            args.pilot,
            args.pilot_sha256,
            args.preflight,
            args.preflight_sha256,
            args.census,
            args.census_sha256,
            args.output,
        )
        payload = melody.encoded({"source_manifest_sha256": pin})
    else:
        if args.output is not None and (
            args.output.resolve().is_relative_to(args.source.resolve())
            or args.output.resolve() == args.query.resolve()
        ):
            raise ValueError("result output overlaps inputs")
        request = melody._json(melody.read_pinned(args.query, args.query_sha256, MAX_JSON))  # noqa: SLF001 -- Strict duplicate-key JSON parser.
        result = melody.search_contour(
            melody.load_source(args.source, args.source_sha256), request, limit=args.limit
        )
        payload = melody.encoded(result)
        if len(payload) > MAX_JSON:
            raise ValueError("query result exceeds 1 MB cap")
        if args.output is not None:
            _publish(args.output, payload)
            payload = melody.encoded({"result_sha256": hashlib.sha256(payload).hexdigest()})
    print(payload.decode().rstrip())  # noqa: T201 -- Explicit local research result.


if __name__ == "__main__":
    main()
