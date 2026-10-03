"""Leakage, unknown-label and sparse-calibration contracts for source completion."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.ml.wikidata_artist_completion import (
    Artist,
    calibrate,
    events,
    fit,
    load_artists,
    masked,
    metrics,
    split,
)


def training() -> list[Artist]:
    """Return overlapping positive statements with adequate training support."""
    return [Artist(f"train-{index}", f"Q{index}", ("Q1", "Q2"), "train") for index in range(10)]


def source_fixture(
    root: Path,
    *,
    projection_qid: str = "Q1",
    license_id: str = "CC0-1.0",
    omit_projection_artist: bool = False,
) -> None:
    """Seal bytes whose raw statement cannot be faked by rehashing projection."""
    mbid = "a0000000-0000-4000-8000-000000000001"
    native_claim = {
        "rank": "normal",
        "mainsnak": {
            "snaktype": "value",
            "datavalue": {"type": "wikibase-entityid", "value": {"id": "Q1"}},
        },
    }
    body = json.dumps(
        {
            "entities": {
                "Q7": {
                    "id": "Q7",
                    "type": "item",
                    "claims": {
                        "P136": [native_claim],
                        "P434": [
                            {
                                "rank": "normal",
                                "mainsnak": {"snaktype": "value", "datavalue": {"value": mbid}},
                            }
                        ],
                    },
                }
            }
        }
    ).encode()
    body_sha = hashlib.sha256(body).hexdigest()
    (root / "raw.json").write_bytes(body)
    projection = {
        "license": license_id,
        "revision": "wikidata-entity-evidence-v1",
        "artists": [
            {
                "artist_mbid": mbid,
                "wikidata_qid": "Q7",
                "name": "Test artist",
                "status": "exact_identity",
                "raw_path": "raw.json",
                "raw_sha256": body_sha,
                "claims": {
                    "P136": [
                        {
                            "datavalue": {
                                "type": "wikibase-entityid",
                                "value": {"id": projection_qid},
                            }
                        }
                    ]
                },
            }
        ],
    }
    if omit_projection_artist:
        projection["artists"] = []
    (root / "projection.json").write_text(json.dumps(projection))
    captures = [
        {
            "admitted": True,
            "kind": "artists",
            "index": 0,
            "body_complete": True,
            "http_status": 200,
            "endpoint": "https://www.wikidata.org/w/api.php",
            "params": {
                "action": "wbgetentities",
                "ids": "Q7",
                "format": "json",
                "props": "claims|labels",
                "maxlag": "5",
                "languages": "en|es|fr|de|ja|zh|pt|ar|ru|hi|ko|it|id|tr|pl|sv",
            },
            "requested": ["Q7"],
            "raw_path": "raw.json",
            "bytes": len(body),
            "sha256": body_sha,
        }
    ]
    (root / "captures.json").write_text(json.dumps(captures))
    (root / "selection.json").write_text(
        json.dumps(
            {"artists": [{"artist_mbid": mbid, "wikidata_qid": "Q7", "name": "Test artist"}]}
        )
    )
    inventory = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in root.iterdir()
    }
    (root / "receipt.json").write_text(
        json.dumps({"files": inventory, "revision": "wikidata-entity-evidence-v1"})
    )


class ArtistCompletionTests(unittest.TestCase):
    """Exercise source completion independently of network and large packs."""

    def test_held_out_targets_cannot_change_fitted_counts(self) -> None:
        """Poison confirmation targets without altering any train-only parameters."""
        original = fit(training(), {})
        poisoned = fit([*training(), Artist("held", "Q99", ("Q999",), "confirmation")], {})
        assert poisoned.support == original.support
        assert poisoned.pairs == original.pairs
        assert poisoned.vocabulary == original.vocabulary
        assert "Q999" not in poisoned.vocabulary

    def test_every_exact_held_out_query_stays_in_denominators(self) -> None:
        """Zero/one-positive and unknown-target rows must remain visible abstentions."""
        model = fit(training(), {})
        artists = [
            Artist("empty", "Q10", (), "confirmation"),
            Artist("single", "Q11", ("Q1",), "confirmation"),
            Artist("cold", "Q12", ("Q998", "Q999"), "confirmation"),
        ]
        rows = events(artists, model, "confirmation", "combined")
        result = metrics(rows, calibrate([]))
        assert result["all_exact_artist_queries"] == len(artists)
        assert result["masked_observed_positive_queries"] == len(artists) - 1
        assert result["unlabelled_queries"] == 1
        assert result["one_positive_queries"] == 1
        assert result["unseen_target_queries"] == 1
        assert result["recall"]["10"] == 0.0
        assert result["abstentions"] == {
            "unlabelled": 1,
            "no_observed_seed": 1,
            "unsupported_or_disconnected_seed": 1,
        }

    def test_calibration_sparse_bins_abstain(self) -> None:
        """A single apparent success cannot manufacture a trustworthy probability."""
        bins = calibrate([{"ranked": [("Q1", 0.5)], "masked_observed_target": "Q1"}])
        assert bins[3]["count"] == 1
        assert bins[3]["probability"] is None
        assert bins[0]["interval_95"] == [0.0, 1.0]

    def test_typed_parent_never_emits_unseen_training_labels(self) -> None:
        """An external typed graph cannot bypass the training-only target vocabulary."""
        model = fit(training(), {"Q1": ("Q2", "Q999")})
        assert model.rank(("Q1",), "typed_parent") == [("Q2", 1.0)]

    def test_mask_is_frozen_and_never_keeps_target_in_seeds(self) -> None:
        """Target masking is deterministic per exact identity, with overlap retained."""
        artist = Artist("identity", "Q42", ("Q1", "Q2", "Q3"), "confirmation")
        seeds, target = masked(artist)
        assert (seeds, target) == masked(artist)
        assert target not in seeds
        assert set(seeds) | {target} == set(artist.labels)
        assert split(artist.mbid) == split(artist.mbid)

    def test_candidate_scoring_does_not_mutate_training_pairs(self) -> None:
        """Confirmation ranking cannot append zero-valued parameters to the model."""
        model = fit(training(), {})
        before = {key: dict(value) for key, value in model.pairs.items()}
        model.rank(("Q1", "Q999"), "combined")
        assert before == {key: dict(value) for key, value in model.pairs.items()}

    def test_raw_source_replay_rejects_self_rehashed_projection(self) -> None:
        """A coherent manifest cannot turn an invented genre into a native fact."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            source_fixture(Path(directory), projection_qid="Q999")
            with self.assertRaisesRegex(ValueError, "raw P136"):
                load_artists(Path(directory))

    def test_exact_raw_source_replay_succeeds(self) -> None:
        """Projection labels and unique UUID must replay the actual entity request."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            source_fixture(Path(directory))
            rows, receipt = load_artists(Path(directory))
            assert rows[0].labels == ("Q1",)
            assert receipt["exact_artists"] == 1

    def test_non_cc0_source_cannot_claim_open_core_eligibility(self) -> None:
        """A sealed inventory cannot silently replace the explicit source licence."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            source_fixture(Path(directory), license_id="CC-BY-NC-4.0")
            with self.assertRaisesRegex(ValueError, "CC0 license"):
                load_artists(Path(directory))

    def test_omitted_query_cannot_be_hidden_by_rehashing_source_projection(self) -> None:
        """Even a zero-positive projected query must exist in the frozen roster."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            source_fixture(Path(directory), omit_projection_artist=True)
            with self.assertRaisesRegex(ValueError, "omitted frozen"):
                load_artists(Path(directory))
