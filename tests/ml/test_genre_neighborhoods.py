"""Focused contract tests for the separate-channel co-listen checkpoint."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.common import canonical_json, sha256_hex
from opennoise.ml.genre_neighborhoods.builder import _build_cache, _channel_observed_states
from opennoise.ml.genre_neighborhoods.contracts import (
    GenreNeighborhoodArtifact,
    GenreNeighborhoodError,
    GenreNeighborhoodInputs,
    GenreNeighborhoodReceipt,
    GenreNeighborhoodSettings,
    artifact_sha256,
)
from opennoise.ml.genre_neighborhoods.query import certify_neighborhood_cache


def _artifact_payload() -> dict[str, object]:
    """Return a minimal valid artifact payload for contract mutation tests."""
    digest = "a" * 64
    return {
        "inputs": tuple(
            {"role": role, "byte_sha256": digest, "byte_count": 1, "logical_sha256": digest}
            for role in (
                "graph_database",
                "graph_receipt",
                "colisten_database",
                "colisten_receipt",
            )
        ),
        "graph_receipt_output_sha256": digest,
        "colisten_receipt_output_sha256": digest,
        "settings": {},
        "settings_sha256": digest,
        "input_sha256": digest,
        "cache_database_sha256": digest,
        "cache_database_byte_count": 1,
        "colisten_artist_count": 0,
        "split": {
            "canonical_artist_pair_count": 0,
            "training_artist_pair_count": 0,
            "heldout_artist_pair_count": 0,
            "training_window_count": 0,
            "heldout_window_count": 0,
        },
        "channels": tuple(
            {
                "channel": channel,
                "membership_count": 0,
                "membership_artist_count": 0,
                "observed_seed_count": 0,
                "training_positive_count": 0,
                "retained_neighbor_count": 0,
                "heldout_positive_count": 0,
                "heldout_scoreable_positive_count": 0,
                "heldout_recovered_at_k_count": 0,
            }
            for channel in ("artist_direct", "reviewed_alias_context")
        ),
        "output_sha256": digest,
    }


class GenreNeighborhoodStateTest(unittest.TestCase):
    """Channel-local state coverage."""

    def test_channel_state_does_not_leak_an_observation_between_evidence_channels(self) -> None:
        """A direct-only claim must not mark the reviewed-alias channel observed."""
        base = {"direct-only": "isolated", "alias-only": "abstained", "neither": "isolated"}
        memberships: dict[str, dict[str, tuple[str, ...]]] = {
            "artist_direct": {"artist-a": ("direct-only",)},
            "reviewed_alias_context": {"artist-b": ("alias-only",)},
        }

        states = _channel_observed_states(base, memberships)

        self.assertEqual(
            states["artist_direct"],
            {"direct-only": "observed", "alias-only": "abstained", "neither": "isolated"},
        )
        self.assertEqual(
            states["reviewed_alias_context"],
            {"direct-only": "isolated", "alias-only": "observed", "neither": "isolated"},
        )

    def test_artifact_rejects_duplicate_channel_rows(self) -> None:
        """A rehashed receipt cannot silently replace one channel with another."""
        payload = _artifact_payload()
        channels = payload["channels"]
        if not isinstance(channels, tuple):
            self.fail("test payload channels must be a tuple")
        payload["channels"] = (channels[0], channels[0])
        with self.assertRaises(ValueError):
            GenreNeighborhoodArtifact.model_validate(payload)

    def test_artifact_rejects_reordered_or_duplicate_input_roles(self) -> None:
        """A receipt cannot relabel one byte-bound source as another input role."""
        payload = _artifact_payload()
        inputs = payload["inputs"]
        if not isinstance(inputs, tuple):
            self.fail("test payload inputs must be a tuple")
        payload["inputs"] = (inputs[0], inputs[0], inputs[2], inputs[3])
        with self.assertRaises(ValueError):
            GenreNeighborhoodArtifact.model_validate(payload)

    def test_build_rejects_membership_for_unknown_seed(self) -> None:
        """Claims outside the certified stable-seed universe never enter the cache."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / "graph.sqlite"
            colisten_path = root / "colisten.sqlite"
            with sqlite3.connect(graph_path) as graph:
                graph.executescript(
                    """
                    CREATE TABLE identity(namespace TEXT, identifier TEXT, disposition TEXT);
                    CREATE TABLE claim(subject_namespace TEXT, subject_identifier TEXT,
                        predicate TEXT, object_namespace TEXT, object_identifier TEXT,
                        evidence_kind TEXT);
                    """
                )
                graph.executemany(
                    "INSERT INTO identity VALUES ('stable_seed', ?, 'observed')",
                    ((f"seed-{index}",) for index in range(6291)),
                )
                graph.execute(
                    "INSERT INTO identity VALUES ('musicbrainz_artist', 'artist-a', 'source')"
                )
                graph.execute(
                    """INSERT INTO claim VALUES ('musicbrainz_artist', 'artist-a',
                    'artist_membership', 'stable_seed', 'not-a-seed', 'artist_direct')"""
                )
            with sqlite3.connect(colisten_path) as colisten:
                colisten.execute(
                    """CREATE TABLE colisten_relation(
                        left_artist_mbid TEXT, right_artist_mbid TEXT,
                        window_start INTEGER, evidence_fingerprint TEXT,
                        distinct_user_count INTEGER)"""
                )
                colisten.execute(
                    "INSERT INTO colisten_relation VALUES "
                    "('artist-a', 'artist-b', 0, 'fingerprint', 5)"
                )
            inputs = GenreNeighborhoodInputs(
                graph_database=graph_path,
                graph_receipt=root / "graph.receipt.json",
                colisten_database=colisten_path,
                colisten_receipt=root / "colisten.receipt.json",
                cache_directory=root / "cache",
            )
            with self.assertRaises(GenreNeighborhoodError):
                _build_cache(root / "cache.sqlite", inputs, GenreNeighborhoodSettings())

    def test_query_certification_rejects_rehashed_artifact_without_receipt_update(self) -> None:
        """Artifact self-hashes cannot replace the independently serialized custody receipt."""
        payload = _artifact_payload()
        artifact = GenreNeighborhoodArtifact.model_validate(payload)
        artifact = artifact.model_copy(update={"output_sha256": artifact_sha256(artifact)})
        serialized = canonical_json(artifact.model_dump(mode="json")) + b"\n"
        receipt = GenreNeighborhoodReceipt(
            artifact_sha256=sha256_hex(serialized),
            artifact_byte_count=len(serialized),
            logical_output_sha256=artifact.output_sha256,
            cache_database_sha256=artifact.cache_database_sha256,
        )
        forged = artifact.model_copy(update={"output_sha256": "b" * 64})
        forged = forged.model_copy(update={"output_sha256": artifact_sha256(forged)})
        with tempfile.NamedTemporaryFile() as database:
            Path(database.name).write_bytes(b"cache")
            with self.assertRaises(GenreNeighborhoodError):
                certify_neighborhood_cache(Path(database.name), forged, receipt)
