from __future__ import annotations

import unittest

from musix.checkpoints.source_neutral_certification import (
    CheckpointCertificationError,
    HierarchyCertification,
    InputBinding,
    MembershipCertification,
    PeerCertification,
    SourceNeutralCheckpointCertification,
    SourceNeutralCheckpointInputs,
    _historical_seed_id,
    _validate_historical_neighbor_endpoints,
    _validate_historical_seed_universe,
    _validate_seed_accounting,
    certification_sha256,
    verify_source_neutral_checkpoint_certification,
)
from musix.peers.audit.strength_aware_peer_audit import (
    ConsensusAbstention,
    ConsensusMicroNeighborhoodAudit,
    EgoAffiliation,
)
from musix.taxonomy.relations.expansion import (
    RelationExpansionCoverage,
    TaxonomyRelationExpansionArtifact,
)


class SourceNeutralCheckpointCertificationTests(unittest.TestCase):
    def test_historical_namespace_bridge_is_exact_and_rejects_malformed_values(self) -> None:
        self.assertEqual(_historical_seed_id("enao-legacy:item1"), "item1")
        for value in ("item1", "enao-legacy:", "enao-legacy:enao-legacy:item1"):
            with self.assertRaises(CheckpointCertificationError):
                _historical_seed_id(value)

    def test_historical_universe_and_neighbors_reject_substitution_and_dangling_rows(self) -> None:
        seeds = {"item1", "item2"}
        _validate_historical_seed_universe(set(seeds), seeds)
        _validate_historical_neighbor_endpoints({("item1", "item2")}, seeds)
        with self.assertRaisesRegex(CheckpointCertificationError, "does not match"):
            _validate_historical_seed_universe({"item1", "item3"}, seeds)
        with self.assertRaisesRegex(CheckpointCertificationError, "dangling"):
            _validate_historical_neighbor_endpoints({("item1", "item3")}, seeds)

    def test_seed_accounting_requires_explicit_consensus_partition(self) -> None:
        seed_ids = {f"seed-{index}" for index in range(6_291)}
        consensus = _consensus(tuple(sorted(seed_ids)))
        taxonomy = _taxonomy()
        _validate_seed_accounting(seed_ids, consensus, taxonomy)
        with self.assertRaisesRegex(CheckpointCertificationError, "explicitly account"):
            _validate_seed_accounting(set(tuple(sorted(seed_ids))[1:]), consensus, taxonomy)

    def test_certification_hash_replays_and_history_cannot_enter_construction_inputs(self) -> None:
        bindings = tuple(
            InputBinding(
                role=role,
                bytes_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            )
            for role in (
                "evidence_graph_database",
                "evidence_graph_receipt",
                "consensus",
                "taxonomy",
            )
        )
        base = SourceNeutralCheckpointCertification(
            inputs=bindings,
            graph_explicit_abstention_row_count=0,
            membership=MembershipCertification(
                certified_observed_seed_count=0, certified_unknown_seed_count=6_291
            ),
            peers=PeerCertification(
                certified_stable_pair_count=0,
                eligible_seed_count=0,
                explicit_abstention_count=6_291,
            ),
            hierarchy=HierarchyCertification(
                accepted_factual_edge_count=0,
                factual_endpoint_seed_count=0,
                factual_isolated_seed_count=6_291,
            ),
            output_sha256="0" * 64,
        )
        certification = base.model_copy(update={"output_sha256": certification_sha256(base)})
        verify_source_neutral_checkpoint_certification(certification)
        with self.assertRaises(CheckpointCertificationError):
            verify_source_neutral_checkpoint_certification(
                certification.model_copy(update={"output_sha256": "0" * 64})
            )
        self.assertNotIn(
            "historical_evaluation", SourceNeutralCheckpointInputs.__dataclass_fields__
        )


def _consensus(seed_ids: tuple[str, ...]) -> ConsensusMicroNeighborhoodAudit:
    return ConsensusMicroNeighborhoodAudit.model_construct(
        eligible_seed_count=1,
        abstention_count=len(seed_ids) - 1,
        ego_affiliations=(
            EgoAffiliation(
                genre_id=seed_ids[0], member_genre_ids=(seed_ids[0],), stable_peer_genre_ids=()
            ),
        ),
        abstentions=tuple(
            ConsensusAbstention(genre_id=seed, reason="no_direct_candidate_endpoint")
            for seed in seed_ids[1:]
        ),
    )


def _taxonomy() -> TaxonomyRelationExpansionArtifact:
    return TaxonomyRelationExpansionArtifact.model_construct(
        edges=(),
        coverage=RelationExpansionCoverage.model_construct(seed_count=6_291),
    )


if __name__ == "__main__":
    unittest.main()
