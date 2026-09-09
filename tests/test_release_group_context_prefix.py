# ruff: noqa: S106

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from musix.serving.release_group_context_prefix import (
    ReleaseGroupContextError,
    TargetMask,
    _iter_prefix,
    _rows_for_release_group,
    load_target_mask,
)
from musix.sources.musicbrainz import MusicBrainzAdapterError, MusicBrainzReleaseGroup


class ReleaseGroupContextPrefixTests(unittest.TestCase):
    def test_target_matcher_uses_production_normalization_and_genre_identity(self) -> None:
        mask = TargetMask(
            frozenset({"genre-id"}),
            frozenset({"hip hop", "intelligent dance music", "idm"}),
            frozenset(),
            6291,
            "a" * 64,
            "b" * 64,
            "c" * 64,
        )
        self.assertTrue(mask.matches(kind="tag", token_id=None, token_name="HIP-HOP"))
        self.assertTrue(mask.matches(kind="tag", token_id=None, token_name="IDM"))
        self.assertTrue(mask.matches(kind="genre", token_id="genre-id", token_name="unrelated"))
        self.assertTrue(mask.matches(kind="genre", token_id="unrelated", token_name="Hip Hop"))
        self.assertFalse(mask.matches(kind="tag", token_id="unrelated", token_name="noise"))

    def test_rows_are_deduplicatable_and_exclude_target_genre_name_even_with_other_id(self) -> None:
        artist = str(uuid4())
        group = MusicBrainzReleaseGroup.model_validate_json(
            json.dumps(
                {
                    "id": str(uuid4()),
                    "title": "fixture",
                    "artist-credit": [{"artist": {"id": artist, "name": "a"}, "name": "a"}],
                    "genres": [{"id": str(uuid4()), "name": "Hip-Hop"}],
                    "tags": [{"name": "noise", "count": 2}, {"name": "noise", "count": 2}],
                }
            )
        )
        mask = TargetMask(
            frozenset(), frozenset({"hip hop"}), frozenset(), 1, "a" * 64, "b" * 64, "c" * 64
        )
        rows = _rows_for_release_group(group, mask)
        self.assertEqual([(row[2], row[4]) for row in rows], [("tag", "noise"), ("tag", "noise")])
        self.assertEqual(len(set(rows)), 1)
        self.assertEqual(rows[0][5], 2)

    def test_rows_reject_nonpositive_source_vote_count(self) -> None:
        group = MusicBrainzReleaseGroup.model_validate_json(
            json.dumps(
                {
                    "id": str(uuid4()),
                    "title": "fixture",
                    "tags": [{"name": "noise", "count": 0}],
                }
            )
        )
        with self.assertRaisesRegex(ReleaseGroupContextError, "count must be positive"):
            _rows_for_release_group(group, None)

    def test_prefix_only_swallows_the_expected_cap_error(self) -> None:
        with patch(
            "musix.serving.release_group_context_prefix.iter_json_archive_lines",
            side_effect=lambda *_args, **_kwargs: _cap_iterator(),
        ):
            self.assertEqual(list(_iter_prefix(Path("fixture"), 2)), [b"one", b"two"])
        with (
            patch(
                "musix.serving.release_group_context_prefix.iter_json_archive_lines",
                side_effect=lambda *_args, **_kwargs: _malformed_iterator(),
            ),
            self.assertRaisesRegex(MusicBrainzAdapterError, "invalid archive"),
        ):
            list(_iter_prefix(Path("fixture"), 2))

    def test_reconciliation_binding_rejects_tampered_seed_target(self) -> None:
        reconciliation = _Artifact("seed", "source", "content", 2, ())
        target = _Artifact("seed", "other-source", "content", 2, ())
        with (
            patch(
                "musix.serving.release_group_context_prefix.load_seed_reconciliation",
                return_value=reconciliation,
            ),
            patch(
                "musix.serving.release_group_context_prefix.load_seed_target_artifact", return_value=target
            ),
            patch("musix.serving.release_group_context_prefix.file_sha256", return_value="a" * 64),
            self.assertRaisesRegex(ValueError, "complete seed binding"),
        ):
            load_target_mask(Path("reconciliation"), Path("target"), Path("aliases"))

    def test_reconciliation_binding_rejects_a_coherent_incomplete_universe(self) -> None:
        reconciliation = _Artifact("seed", "source", "content", 2, ())
        target = _Artifact("seed", "source", "content", 2, ())
        with (
            patch(
                "musix.serving.release_group_context_prefix.load_seed_reconciliation",
                return_value=reconciliation,
            ),
            patch(
                "musix.serving.release_group_context_prefix.load_seed_target_artifact", return_value=target
            ),
            self.assertRaisesRegex(ValueError, "complete 6291-seed universe"),
        ):
            load_target_mask(Path("reconciliation"), Path("target"), Path("aliases"))


class _Artifact:
    def __init__(
        self,
        seed_input_sha256: str,
        seed_source_id: str,
        seed_source_content_sha256: str,
        seed_count: int,
        dispositions: tuple[object, ...],
    ) -> None:
        self.seed_input_sha256 = seed_input_sha256
        self.seed_source_id = seed_source_id
        self.seed_source_content_sha256 = seed_source_content_sha256
        self.seed_count = seed_count
        self.dispositions = dispositions


def _cap_iterator() -> object:
    yield b"one"
    yield b"two"
    raise MusicBrainzAdapterError("MusicBrainz dump exceeds max_records")


def _malformed_iterator() -> object:
    yield b"one"
    raise MusicBrainzAdapterError("invalid archive")
