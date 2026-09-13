from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from musix.projections.consensus_publication import (
    ConsensusSemanticPublication,
    ConsensusSemanticPublicationError,
    ConsensusSemanticPublicationInputs,
    build_consensus_semantic_publication,
    consensus_semantic_publication_sha256,
    verify_consensus_semantic_publication,
    write_consensus_semantic_publication,
)
from tests.projections.test_consensus_semantic import _complete_fixture_projection


class ConsensusSemanticPublicationTests(unittest.TestCase):
    def test_publisher_binds_verified_projection_bytes_and_logical_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "projection.json"
            output = root / "publication.json"
            source.write_text(_complete_fixture_projection().model_dump_json(), encoding="utf-8")
            publication = build_consensus_semantic_publication(
                ConsensusSemanticPublicationInputs(projection_path=source)
            )
            write_consensus_semantic_publication(output, publication)
            verify_consensus_semantic_publication(publication)
            self.assertEqual(
                publication.source_projection.logical_sha256,
                publication.projection.output_sha256,
            )
            self.assertEqual(publication.source_projection.byte_count, source.stat().st_size)
            self.assertTrue(output.exists())

    def test_publication_rejects_nested_projection_logical_mismatch(self) -> None:
        publication = _publication_from_fixture()
        mismatched = publication.model_copy(
            update={
                "source_projection": publication.source_projection.model_copy(
                    update={"logical_sha256": "0" * 64}
                )
            }
        )
        mismatched = mismatched.model_copy(
            update={"output_sha256": consensus_semantic_publication_sha256(mismatched)}
        )
        with self.assertRaisesRegex(ConsensusSemanticPublicationError, "logical binding"):
            verify_consensus_semantic_publication(mismatched)


def _publication_from_fixture() -> ConsensusSemanticPublication:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "projection.json"
        path.write_text(_complete_fixture_projection().model_dump_json(), encoding="utf-8")
        return build_consensus_semantic_publication(
            ConsensusSemanticPublicationInputs(projection_path=path)
        )
