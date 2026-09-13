import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from opennoise.serving.metadata.representative_publication import (
    MetadataRepresentativePublicationError,
    load_metadata_representative_artifact,
    publish_metadata_representatives,
)
from opennoise.serving.metadata.representatives import (
    MetadataRepresentativeArtifact,
    MetadataRepresentativeItem,
    RepresentativeRunProvenance,
)
from opennoise.storage import LocalObjectStore


def _artifact() -> MetadataRepresentativeArtifact:
    return MetadataRepresentativeArtifact(
        run=RepresentativeRunProvenance(
            model_run_id=7,
            output_sha256="a" * 64,
            input_provenance_ids=(11, 12),
        ),
        items=(
            MetadataRepresentativeItem(
                genre_id="wikidata:genre:Q100",
                entity_kind="release_group",
                entity_id="musicbrainz:release-group:11111111-1111-4111-8111-111111111111",
                display_name="Album A",
                rank=1,
                direct_evidence_value=2.0,
                source_count=2,
                evidence_refs=("catalog:metadata:1",),
            ),
            MetadataRepresentativeItem(
                genre_id="wikidata:genre:Q100",
                entity_kind="recording",
                entity_id="musicbrainz:recording:22222222-2222-4222-8222-222222222222",
                display_name="Track A",
                rank=1,
                direct_evidence_value=1.0,
                source_count=1,
                evidence_refs=("catalog:metadata:2",),
            ),
        ),
    )


class MetadataRepresentativePublicationTests(unittest.TestCase):
    def test_persists_verified_examples_under_a_content_addressed_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "metadata-representatives.json"
            artifact_path.write_text(_artifact().model_dump_json(), encoding="utf-8")
            store = LocalObjectStore(root / "objects")

            receipt = publish_metadata_representatives(artifact_path, store)
            replay = publish_metadata_representatives(artifact_path, store)

        self.assertEqual(receipt.run.model_run_id, 7)
        self.assertEqual(receipt.total_examples, 2)
        self.assertEqual(receipt.release_group_examples, 1)
        self.assertEqual(receipt.recording_examples, 1)
        self.assertEqual(receipt.release_group_genres, 1)
        self.assertEqual(receipt.recording_genres, 1)
        self.assertEqual(receipt.content_policy, "metadata_only_no_audio_or_preview_urls")
        self.assertTrue(receipt.artifact.key.value.startswith("metadata-representatives/sha256/"))
        self.assertFalse(receipt.artifact.reused)
        self.assertTrue(replay.artifact.reused)

    def test_boundary_rejects_media_and_unsafe_catalog_references(self) -> None:
        with self.assertRaises(ValidationError):
            MetadataRepresentativeItem(
                genre_id="wikidata:genre:Q100",
                entity_kind="recording",
                entity_id="https://example.test/preview.mp3",
                display_name="Unsafe",
                rank=1,
                direct_evidence_value=1.0,
                source_count=1,
                evidence_refs=("catalog:metadata:1",),
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.mp3"
            path.write_bytes(b"not media metadata")
            with self.assertRaises(MetadataRepresentativePublicationError):
                load_metadata_representative_artifact(path)

    def test_boundary_rejects_extra_payload_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata-representatives.json"
            payload = _artifact().model_dump(mode="json")
            payload["media_url"] = "https://example.test/preview.mp3"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MetadataRepresentativePublicationError):
                load_metadata_representative_artifact(path)


if __name__ == "__main__":
    unittest.main()
