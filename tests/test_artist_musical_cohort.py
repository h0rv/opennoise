"""Frozen identity, method blinding and unknown-access musical-review contracts."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, override
from unittest.mock import patch
from uuid import UUID

from opennoise.ml.wikidata_artist_completion import Model, split
from opennoise.ml.wikidata_unconditional_prior import rank_prior
from opennoise.review.artist_musical_cohort import (
    CONTEXT_PROPERTIES,
    FIRST_BATCH,
    blind_candidates,
    census,
    frozen_roster,
    opaque_id,
    public_item,
    render_review,
    reviewer_slots,
    verify_bindings,
    write,
)


def confirmation_rows() -> list[dict[str, Any]]:
    """Create explicit synthetic fixture identities; these are never human evidence."""
    result = []
    index = 1
    while len(result) < FIRST_BATCH + 2:
        mbid = str(UUID(int=index))
        if split(mbid) == "confirmation":
            result.append(
                {
                    "artist_mbid": mbid,
                    "wikidata_qid": f"Q{index}",
                    "split": "confirmation",
                    "observed_genre_qids": [],
                    "masked_observed_target": None,
                }
            )
        index += 1
    return result


def model() -> Model:
    """Use a tiny source-count fixture without fitting from review outcomes."""
    return Model(
        Counter({"Q1": 10, "Q2": 5}), {"Q1": Counter({"Q2": 3})}, ("Q1", "Q2"), {"Q1": ("Q2",)}, 10
    )


class MusicalCohortTests(unittest.TestCase):
    """Exercise review custody and denominator safeguards without large packs."""

    @classmethod
    @override
    def setUpClass(cls) -> None:
        """Prepare bounded deterministic synthetic identities once."""
        cls.fixture = confirmation_rows()

    def test_full_roster_retains_unlabelled_and_cold_queries(self) -> None:
        """No source label/status condition can silently drop a review identity."""
        with patch("opennoise.review.artist_musical_cohort.rows", return_value=iter(self.fixture)):
            result = frozen_roster(Path("unused"))
        assert len(result) == len(self.fixture)
        assert all(row["observed_genre_qids"] == [] for row in result)

    def test_roster_order_is_independent_of_target_labels(self) -> None:
        """Changing fixture target labels cannot affect identity-only ordering."""
        altered = [
            {**row, "observed_genre_qids": ["Q999"], "masked_observed_target": "Q999"}
            for row in reversed(self.fixture)
        ]
        with patch("opennoise.review.artist_musical_cohort.rows", return_value=iter(self.fixture)):
            original = frozen_roster(Path("unused"))
        with patch("opennoise.review.artist_musical_cohort.rows", return_value=iter(altered)):
            changed = frozen_roster(Path("unused"))
        assert [row["artist_mbid"] for row in original] == [row["artist_mbid"] for row in changed]

    def test_duplicate_identity_is_rejected(self) -> None:
        """A duplicated artist cannot inflate independent listener coverage."""
        with (
            patch(
                "opennoise.review.artist_musical_cohort.rows",
                return_value=iter([*self.fixture, self.fixture[0]]),
            ),
            self.assertRaisesRegex(ValueError, "identity/split"),
        ):
            frozen_roster(Path("unused"))

    def test_changed_split_is_rejected(self) -> None:
        """A self-rehashed assignment cannot move artists into the review cohort."""
        forged = [{**self.fixture[0], "split": "train"}, *self.fixture[1:]]
        with (
            patch("opennoise.review.artist_musical_cohort.rows", return_value=iter(forged)),
            self.assertRaisesRegex(ValueError, "identity/split"),
        ):
            frozen_roster(Path("unused"))

    def test_small_cohort_cannot_claim_one_thousand_queries(self) -> None:
        """The requested review denominator must actually exist."""
        with (
            patch(
                "opennoise.review.artist_musical_cohort.rows", return_value=iter(self.fixture[:1])
            ),
            self.assertRaisesRegex(ValueError, "1000"),
        ):
            frozen_roster(Path("unused"))

    def test_public_prompt_has_no_method_assignment_or_truth(self) -> None:
        """A coordinator assignment cannot leak into the public candidate schema."""
        prompt = public_item(
            "query",
            {
                "item_id": "item",
                "genre_qid": "Q1",
                "coordinator_methods": ["combined"],
                "score": 0.9,
            },
            {"Q1": "genre"},
        )
        assert "coordinator_methods" not in prompt
        assert "score" not in prompt
        assert prompt["candidate_is_truth"] is False
        assert prompt["musical_probability"] is None

    def test_blinding_uses_private_key_and_preserves_equal_candidates(self) -> None:
        """Opaque item IDs remain consistent within one sealed private key."""
        assert opaque_id(b"secret", "query:Q1") == opaque_id(b"secret", "query:Q1")
        assert opaque_id(b"secret", "query:Q1") != opaque_id(b"other", "query:Q1")
        candidates, _ = blind_candidates(model(), ("Q1",), b"secret", "query")
        assert len(candidates) == 1
        assert set(candidates[0]["coordinator_methods"]) == {
            "popularity",
            "co_observation",
            "typed_parent",
            "combined",
            "unconditional_training_prior",
        }

    def test_unconditional_prior_predicts_without_supported_seed(self) -> None:
        """The meaningful prior cannot inherit the frozen conditional-arm gap."""
        assert model().rank((), "popularity") == []
        assert rank_prior(model(), ())[0][0] == "Q1"
        candidates, abstentions = blind_candidates(model(), ("Q999",), b"secret", "query")
        assert candidates[0]["coordinator_methods"] == ["unconditional_training_prior"]
        assert set(abstentions) == {"popularity", "co_observation", "typed_parent", "combined"}

    def test_unlabelled_context_census_never_invents_unseen_target(self) -> None:
        """No target is an abstention, never a made-up unseen musical annotation."""
        row = self.fixture[0]
        contexts = {
            row["artist_mbid"]: {"native_context": {prop: [] for prop in CONTEXT_PROPERTIES}}
        }
        result = census([row], contexts, model())
        assert result["source_label_strata"] == {"unlabelled": 1}
        assert result["masked_source_target_support_strata"] == {"unlabelled_no_masked_target": 1}
        assert result["missing_native_context_queries"]["P27"] == 1

    def test_reviewer_slots_contain_no_fictional_people(self) -> None:
        """Assignments and consent remain blank until real independent volunteers exist."""
        slots = reviewer_slots()
        assert len(slots) == len({"reviewer_slot_1", "reviewer_slot_2"})
        assert all(slot["actual_reviewer_id"] is None and slot["consent"] is None for slot in slots)

    def test_model_binding_is_prescribed_not_self_asserted(self) -> None:
        """An arbitrary coherent receipt cannot substitute for the frozen source experiment."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            (root / "receipt.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "prescribed frozen"):
                verify_bindings(root, root, root, "wrong")

    def test_streamed_public_form_and_abstention_rows_exclude_keys(self) -> None:
        """Every query retains two blank rows while private assignment keys stay separate."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            root = Path(directory)
            public, private = root / "public", root / "private"
            public.mkdir()
            private.mkdir()
            source = self.fixture[0]
            roster = [{"query_id": "query", "artist_mbid": source["artist_mbid"]}]
            context = {
                source["artist_mbid"]: {
                    "name": "Synthetic fixture",
                    "native_context": {prop: [] for prop in CONTEXT_PROPERTIES},
                }
            }
            empty = Model(Counter(), {}, (), {}, 1)
            summary = render_review(public, private, [source], roster, context, {}, empty, {})
            assert summary["blank_review_rows"] == len(reviewer_slots())
            assert summary["all_methods_abstained_queries"] == 1
            text = "".join(path.read_text() for path in public.iterdir())
            for forbidden in (
                "secret_hex",
                "coordinator_methods",
                "source_observed_labels_not_truth",
                "masked_source_target_not_truth",
                "method_abstentions",
            ):
                assert forbidden not in text
            assert json.loads((public / "queries.jsonl").read_text())["playback_verified"] is False

    def test_writes_refuse_existing_files(self) -> None:
        """Packet construction cannot overwrite an earlier freeze or recovery artifact."""
        with TemporaryDirectory(dir="/dev/shm") as directory:
            path = Path(directory) / "frozen.json"
            write(path, {"original": True})
            with self.assertRaises(FileExistsError):
                write(path, {"replacement": True})
            assert json.loads(path.read_text()) == {"original": True}
