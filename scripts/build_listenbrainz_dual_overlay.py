"""Build separate receipt-bound ListenBrainz review and aggregate co-listen sidecars."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from opennoise.common import sha256_file
from opennoise.evidence.listenbrainz_overlay import (
    CoListenOverlayInputs,
    CoListenOverlaySources,
    DerivedReviewOverlayInputs,
    DerivedReviewOverlaySources,
    PrivacyPolicy,
    build_colisten_overlay,
    build_derived_review_overlay,
    certify_colisten_overlay_sources,
    certify_derived_review_overlay_sources,
    load_colisten_overlay,
    load_derived_review_overlay,
    write_colisten_overlay,
    write_derived_review_overlay,
)

if TYPE_CHECKING:
    from opennoise.evidence.listenbrainz_overlay.contracts import SidecarInput


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph-database", type=Path, default=Path(".cache/evidence-graph-v2.sqlite")
    )
    parser.add_argument(
        "--graph-receipt", type=Path, default=Path(".cache/evidence-graph-v2.receipt.json")
    )
    parser.add_argument(
        "--propagation-artifact",
        type=Path,
        default=Path(".cache/listenbrainz-propagation-v2/artifact.json"),
    )
    parser.add_argument(
        "--propagation-receipt",
        type=Path,
        default=Path(".cache/listenbrainz-propagation-v2/receipt.json"),
    )
    parser.add_argument(
        "--qualified-listenbrainz-database",
        type=Path,
        default=Path(
            ".cache/listenbrainz-qualified-input/sha256/"
            "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite"
        ),
    )
    parser.add_argument(
        "--qualified-listenbrainz-database-sha256",
        default="282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866",
    )
    parser.add_argument(
        "--derived-review-database",
        type=Path,
        default=Path(".cache/listenbrainz-dual-overlay-v1/derived-review.sqlite"),
    )
    parser.add_argument(
        "--derived-review-receipt",
        type=Path,
        default=Path(".cache/listenbrainz-dual-overlay-v1/derived-review.receipt.json"),
    )
    parser.add_argument(
        "--colisten-database",
        type=Path,
        default=Path(".cache/listenbrainz-dual-overlay-v1/colisten.sqlite"),
    )
    parser.add_argument(
        "--colisten-receipt",
        type=Path,
        default=Path(".cache/listenbrainz-dual-overlay-v1/colisten.receipt.json"),
    )
    parser.add_argument("--minimum-distinct-user-count", type=int, default=5)
    return parser


def main() -> None:
    """Build each non-interchangeable sidecar and write its own receipt."""
    arguments = _parser().parse_args()
    outputs = (
        arguments.derived_review_database,
        arguments.derived_review_receipt,
        arguments.colisten_database,
        arguments.colisten_receipt,
    )
    if all(path.exists() for path in outputs):
        _verify_existing(arguments)
        return
    if any(path.exists() for path in outputs):
        raise ValueError("ListenBrainz overlay outputs are partial; use a fresh output directory")
    started = monotonic()
    sys.stderr.write("ListenBrainz overlay: building derived-review sidecar\n")
    derived = build_derived_review_overlay(
        DerivedReviewOverlayInputs(
            graph_database=arguments.graph_database,
            graph_receipt=arguments.graph_receipt,
            propagation_artifact=arguments.propagation_artifact,
            propagation_receipt=arguments.propagation_receipt,
            output_database=arguments.derived_review_database,
        )
    )
    write_derived_review_overlay(arguments.derived_review_receipt, derived)
    sys.stderr.write("ListenBrainz overlay: building aggregate co-listen sidecar\n")
    colisten = build_colisten_overlay(
        CoListenOverlayInputs(
            graph_database=arguments.graph_database,
            graph_receipt=arguments.graph_receipt,
            qualified_listenbrainz_database=arguments.qualified_listenbrainz_database,
            expected_qualified_database_sha256=arguments.qualified_listenbrainz_database_sha256,
            output_database=arguments.colisten_database,
            privacy=PrivacyPolicy(
                minimum_distinct_user_count=arguments.minimum_distinct_user_count
            ),
        )
    )
    write_colisten_overlay(arguments.colisten_receipt, colisten)
    elapsed = monotonic() - started
    sys.stderr.write(f"ListenBrainz overlay: completed in {elapsed:.1f}s\n")
    sys.stdout.write(
        "{\n"
        f'  "derived_review": {derived.model_dump_json()},\n'
        f'  "colisten": {colisten.model_dump_json()}\n'
        "}\n"
    )


def _verify_existing(arguments: argparse.Namespace) -> None:
    """Verify a complete default checkpoint and all source bytes without rebuilding it."""
    derived = load_derived_review_overlay(arguments.derived_review_receipt)
    colisten = load_colisten_overlay(arguments.colisten_receipt)
    certify_derived_review_overlay_sources(
        DerivedReviewOverlaySources(arguments.derived_review_database, derived)
    )
    certify_colisten_overlay_sources(CoListenOverlaySources(arguments.colisten_database, colisten))
    _verify_inputs(
        derived.inputs,
        {
            "evidence_graph_database": arguments.graph_database,
            "evidence_graph_receipt": arguments.graph_receipt,
            "listenbrainz_propagation_artifact": arguments.propagation_artifact,
            "listenbrainz_propagation_receipt": arguments.propagation_receipt,
        },
    )
    _verify_inputs(
        colisten.inputs,
        {
            "evidence_graph_database": arguments.graph_database,
            "evidence_graph_receipt": arguments.graph_receipt,
            "qualified_listenbrainz_database": arguments.qualified_listenbrainz_database,
        },
    )
    if colisten.privacy.minimum_distinct_user_count != arguments.minimum_distinct_user_count:
        raise ValueError("existing co-listen checkpoint has a different privacy threshold")
    sys.stderr.write("ListenBrainz overlay: existing checkpoint and inputs verified\n")
    sys.stdout.write(
        "{\n"
        f'  "derived_review": {derived.model_dump_json()},\n'
        f'  "colisten": {colisten.model_dump_json()}\n'
        "}\n"
    )


def _verify_inputs(inputs: tuple[SidecarInput, ...], paths: dict[str, Path]) -> None:
    """Check all exactly named source bytes against a persisted sidecar receipt."""
    for item in inputs:
        path = paths[item.role]
        if sha256_file(path) != (item.byte_sha256, item.byte_count):
            raise ValueError(f"existing checkpoint input changed: {item.role}")


if __name__ == "__main__":
    main()
