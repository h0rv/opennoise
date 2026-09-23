"""Write one local pending MusicBrainz direct static policy-review input."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_static_policy_review import (
    build_musicbrainz_direct_static_policy_review_input,
    write_musicbrainz_direct_static_policy_review_input,
)


def main() -> None:
    """Write a create-only local review file and print its byte SHA-256."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct-custody-receipt", type=Path, required=True)
    parser.add_argument("--direct-custody-object-store", type=Path, required=True)
    parser.add_argument("--local-candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=local_cache_output, required=True)
    arguments = parser.parse_args()
    review = build_musicbrainz_direct_static_policy_review_input(
        direct_custody_receipt_path=arguments.direct_custody_receipt,
        direct_custody_object_store=arguments.direct_custody_object_store,
        local_candidate_manifest_path=arguments.local_candidate_manifest,
    )
    print(write_musicbrainz_direct_static_policy_review_input(arguments.output, review))  # noqa: T201


def local_cache_output(value: str) -> Path:
    """Accept only a non-symlink output path under this repository's cache."""
    output = Path(value)
    absolute_output = output.absolute()
    resolved_output = output.resolve()
    cache_directory = Path(__file__).resolve().parent.parent / ".cache"
    if absolute_output != resolved_output:
        raise argparse.ArgumentTypeError("output path must not use a symlink")
    try:
        resolved_output.relative_to(cache_directory.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "output path must be under the repository .cache directory"
        ) from error
    return output


if __name__ == "__main__":
    main()
