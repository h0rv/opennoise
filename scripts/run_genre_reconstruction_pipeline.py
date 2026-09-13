"""Run the small, explicit stages of the open genre reconstruction.

Every stage takes immutable JSON artifacts from the previous stage.  Paths are
always supplied by the caller so a newer MusicBrainz snapshot can be run next
to an older one without changing this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Protocol, TypeVar

from opennoise.evidence.reconstruction import ReconstructionInputs
from opennoise.ingest.musicbrainz.coverage import CoverageReport
from opennoise.models.modeling import PublicModelInput
from opennoise.peers.similarity.historical import (
    HistoricalPeerSettings,
    evaluate_peer_similarity_historical,
    publish_historical_peer_evaluation,
)
from opennoise.peers.similarity.similarity import (
    PeerSimilaritySettings,
    build_peer_similarity,
    evaluate_peer_similarity_gate,
)
from opennoise.serving.public.taxonomy_expansion import PublicTaxonomyExpansionArtifact
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.seeds.reconciliation import (
    MusicBrainzIdentityInput,
    build_seed_reconciliation,
    load_seed_reconciliation,
    musicbrainz_identity_input_from_coverage,
    public_model_input_from_reconstruction_reconciliation,
    publish_seed_reconciliation,
    write_seed_reconciliation,
)
from opennoise.taxonomy.seeds.taxonomy import GenreSeedPublicTaxonomyArtifact
from opennoise.taxonomy.seeds.universe import load_seed_input
from opennoise.taxonomy.structure.asymmetric_genre_containment import (
    AsymmetricGenreContainmentPolicy,
    GenreContainmentBridge,
    build_asymmetric_genre_containment_from_reconstruction_inputs,
    write_asymmetric_genre_containment,
)

ModelT = TypeVar("ModelT")
ModelT_co = TypeVar("ModelT_co", covariant=True)


class _JsonModel(Protocol):
    def model_dump(self, *, mode: str) -> object: ...


class _JsonModelType(Protocol[ModelT_co]):
    @classmethod
    def model_validate_json(cls, json_data: bytes) -> ModelT_co: ...


def _load[ModelT](path: Path, model_type: _JsonModelType[ModelT]) -> ModelT:
    return model_type.model_validate_json(path.read_bytes())


def _write_json(path: Path, value: _JsonModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _reconcile(arguments: argparse.Namespace) -> int:
    seed = load_seed_input(arguments.seed_artifact)
    taxonomy = _load(arguments.taxonomy_artifact, GenreSeedPublicTaxonomyArtifact)
    musicbrainz = (
        _load(arguments.musicbrainz_input, MusicBrainzIdentityInput)
        if arguments.musicbrainz_input is not None
        else None
    )
    artifact = build_seed_reconciliation(seed, taxonomy, musicbrainz)
    if arguments.object_store is not None:
        receipt, stored = publish_seed_reconciliation(
            artifact,
            output_path=arguments.output,
            store=LocalObjectStore(arguments.object_store),
        )
        summary: object = {
            "artifact": artifact.coverage,
            "publication": receipt,
            "object": stored,
        }
    else:
        byte_sha = write_seed_reconciliation(artifact, arguments.output)
        summary = {"artifact": artifact.coverage, "artifact_sha256": byte_sha}
    sys.stdout.write(json.dumps(summary, default=_json_default, indent=2, sort_keys=True) + "\n")
    return 0


def _musicbrainz_input(arguments: argparse.Namespace) -> int:
    coverage = _load(arguments.coverage, CoverageReport)
    seed = load_seed_input(arguments.seed_artifact)
    identity_input = musicbrainz_identity_input_from_coverage(coverage, seed)
    _write_json(arguments.output, identity_input)
    sys.stdout.write(identity_input.model_dump_json(indent=2) + "\n")
    return 0


def _bridge_input(arguments: argparse.Namespace) -> int:
    reconstruction = _load(arguments.reconstruction_inputs, ReconstructionInputs)
    reconciliation = load_seed_reconciliation(arguments.reconciliation)
    model_input, report = public_model_input_from_reconstruction_reconciliation(
        reconstruction, reconciliation
    )
    _write_json(arguments.output, model_input)
    _write_json(arguments.report, report)
    sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return 0


def _containment(arguments: argparse.Namespace) -> int:
    taxonomy = _load(arguments.taxonomy_expansion, PublicTaxonomyExpansionArtifact)
    reconstruction = _load(arguments.reconstruction_inputs, ReconstructionInputs)
    bridge = _load(arguments.bridge, GenreContainmentBridge)
    policy = AsymmetricGenreContainmentPolicy(
        minimum_child_artist_count=arguments.minimum_child_artist_count,
        minimum_parent_artist_count=arguments.minimum_parent_artist_count,
        minimum_shared_artist_count=arguments.minimum_shared_artist_count,
        minimum_child_coverage=arguments.minimum_child_coverage,
        minimum_directionality_gap=arguments.minimum_directionality_gap,
        maximum_taxonomy_edges=arguments.maximum_taxonomy_edges,
    )
    artifact = build_asymmetric_genre_containment_from_reconstruction_inputs(
        taxonomy, reconstruction, bridge, policy
    )
    receipt = write_asymmetric_genre_containment(
        artifact,
        output=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


def _peer(arguments: argparse.Namespace) -> int:
    public_input = _load(arguments.public_input, PublicModelInput)
    seed_reconciliation = (
        load_seed_reconciliation(arguments.seed_reconciliation)
        if arguments.seed_reconciliation is not None
        else None
    )
    settings = PeerSimilaritySettings(
        metric=arguments.metric,
        minimum_shared_artists=arguments.minimum_shared_artists,
        minimum_aggregate_support=arguments.minimum_aggregate_support,
        minimum_aggregate_windows=arguments.minimum_aggregate_windows,
        direct_component_weight=arguments.direct_component_weight,
        aggregate_component_weight=arguments.aggregate_component_weight,
        maximum_neighbors=arguments.maximum_neighbors,
        maximum_candidate_pairs=arguments.maximum_candidate_pairs,
        maximum_pair_visits=arguments.maximum_pair_visits,
    )
    artifact = build_peer_similarity(
        public_input, settings, seed_reconciliation=seed_reconciliation
    )
    gate = evaluate_peer_similarity_gate(artifact, public_input, settings)
    if not gate.passed:
        raise ValueError("peer similarity gate failed: " + "; ".join(gate.failures))
    _write_json(arguments.output, artifact)
    if arguments.gate_report is not None:
        _write_json(arguments.gate_report, gate)
    sys.stdout.write(json.dumps(gate.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")
    return 0


def _peer_evaluate(arguments: argparse.Namespace) -> int:
    candidate_settings = PeerSimilaritySettings(
        metric=arguments.metric,
        minimum_shared_artists=arguments.minimum_shared_artists,
        minimum_aggregate_support=arguments.minimum_aggregate_support,
        minimum_aggregate_windows=arguments.minimum_aggregate_windows,
        direct_component_weight=arguments.direct_component_weight,
        aggregate_component_weight=arguments.aggregate_component_weight,
        maximum_neighbors=arguments.maximum_neighbors,
        maximum_candidate_pairs=arguments.maximum_candidate_pairs,
        maximum_pair_visits=arguments.maximum_pair_visits,
    )
    report = evaluate_peer_similarity_historical(
        arguments.candidate,
        arguments.public_input,
        arguments.public_database,
        arguments.historical_database,
        candidate_settings=candidate_settings,
        settings=HistoricalPeerSettings(
            k=arguments.k,
            minimum_shared_artists=arguments.historical_minimum_shared_artists,
        ),
    )
    _write_json(arguments.output, report)
    publication = publish_historical_peer_evaluation(
        arguments.output, report, LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(publication.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(publication.model_dump_json(indent=2) + "\n")
    return 0


def _json_default(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _add_peer_settings(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--metric", choices=("weighted_jaccard", "cosine"), default="weighted_jaccard"
    )
    parser.add_argument("--minimum-shared-artists", type=int, default=2)
    parser.add_argument("--minimum-aggregate-support", type=int, default=2)
    parser.add_argument("--minimum-aggregate-windows", type=int, default=1)
    parser.add_argument("--direct-component-weight", type=float, default=0.7)
    parser.add_argument("--aggregate-component-weight", type=float, default=0.3)
    parser.add_argument("--maximum-neighbors", type=int, default=25)
    parser.add_argument("--maximum-candidate-pairs", type=int, default=500_000)
    parser.add_argument("--maximum-pair-visits", type=int, default=5_000_000)


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    """Build the explicit stage parser for tests and shell completion."""
    parser = argparse.ArgumentParser(prog="run-genre-reconstruction")
    commands = parser.add_subparsers(dest="command", required=True)

    reconcile = commands.add_parser("reconcile", help="seal all seed identity dispositions")
    reconcile.add_argument("--seed-artifact", type=Path, required=True)
    reconcile.add_argument("--taxonomy-artifact", type=Path, required=True)
    reconcile.add_argument("--musicbrainz-input", type=Path)
    reconcile.add_argument("--output", type=Path, required=True)
    reconcile.add_argument("--object-store", type=Path)
    reconcile.set_defaults(handler=_reconcile)

    musicbrainz_input = commands.add_parser(
        "musicbrainz-input", help="adapt coverage matches into stable seed identity rows"
    )
    musicbrainz_input.add_argument("--coverage", type=Path, required=True)
    musicbrainz_input.add_argument("--seed-artifact", type=Path, required=True)
    musicbrainz_input.add_argument("--output", type=Path, required=True)
    musicbrainz_input.set_defaults(handler=_musicbrainz_input)

    bridge = commands.add_parser("bridge-input", help="join source edges to stable seed IDs")
    bridge.add_argument("--reconstruction-inputs", type=Path, required=True)
    bridge.add_argument("--reconciliation", type=Path, required=True)
    bridge.add_argument("--output", type=Path, required=True)
    bridge.add_argument("--report", type=Path, required=True)
    bridge.set_defaults(handler=_bridge_input)

    containment = commands.add_parser("containment", help="build directed taxonomy candidates")
    containment.add_argument("--taxonomy-expansion", type=Path, required=True)
    containment.add_argument("--reconstruction-inputs", type=Path, required=True)
    containment.add_argument("--bridge", type=Path, required=True)
    containment.add_argument("--output", type=Path, required=True)
    containment.add_argument("--object-store", type=Path, required=True)
    containment.add_argument("--receipt", type=Path, required=True)
    containment.add_argument("--minimum-child-artist-count", type=int, default=2)
    containment.add_argument("--minimum-parent-artist-count", type=int, default=2)
    containment.add_argument("--minimum-shared-artist-count", type=int, default=1)
    containment.add_argument("--minimum-child-coverage", type=float, default=0.75)
    containment.add_argument("--minimum-directionality-gap", type=float, default=0.10)
    containment.add_argument("--maximum-taxonomy-edges", type=int, default=100_000)
    containment.set_defaults(handler=_containment)

    peer = commands.add_parser("peer", help="build symmetric peers and directional top-k")
    peer.add_argument("--public-input", type=Path, required=True)
    peer.add_argument("--output", type=Path, required=True)
    peer.add_argument("--gate-report", type=Path)
    peer.add_argument(
        "--seed-reconciliation",
        type=Path,
        help="attach the verified all-seed reconciliation to the peer artifact",
    )
    _add_peer_settings(peer)
    peer.set_defaults(handler=_peer)

    evaluate = commands.add_parser("peer-evaluate", help="compare peers with historical H3")
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--public-input", type=Path, required=True)
    evaluate.add_argument("--public-database", type=Path, required=True)
    evaluate.add_argument("--historical-database", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--object-store", type=Path, required=True)
    evaluate.add_argument("--receipt", type=Path, required=True)
    _add_peer_settings(evaluate)
    evaluate.add_argument("--k", type=int, default=25)
    evaluate.add_argument("--historical-minimum-shared-artists", type=int, default=1)
    evaluate.set_defaults(handler=_peer_evaluate)
    return parser


def main() -> int:
    """Run one pipeline stage and print its receipt or gate."""
    arguments = build_parser().parse_args()
    handler = getattr(arguments, "handler", None)
    if not callable(handler):
        raise TypeError("pipeline command did not define a handler")
    result = handler(arguments)
    if not isinstance(result, int):
        raise TypeError("pipeline command handler must return an integer")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
