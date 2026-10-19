"""Synthetic mathematical/source-contract tests; real human targets require a sealed census."""

import hashlib
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_human_genre as genre


def observation(
    identity: int,
    *,
    artist: int | None = None,
    album: int | None = None,
    tags: tuple[str, ...] = (),
    votes: tuple[str, ...] | None = None,
) -> genre.native.Observation:
    """Build canonical synthetic metadata and votes without source bytes."""
    return genre.native.Observation(
        identity,
        artist or identity,
        album or identity,
        f"{identity % 100:02d}/{identity}.mp3",
        "100",
        tags,
        votes,
    )


def supported_rows() -> list[genre.native.Observation]:
    """Construct ten independent components per class, two in each fixed fold."""
    result = []
    identity = 1000
    for name in genre.CLASSES:
        for outer in range(genre.FOLDS):
            for _ in range(2):
                while genre.fold(identity) != outer:
                    identity += 10
                result.extend(
                    observation(
                        identity + offset,
                        artist=identity,
                        album=identity,
                        tags=("genre---" + name, "instrument---guitar"),
                        votes=(name,) * 3,
                    )
                    for offset in range(3)
                )
                identity += 10
    return sorted(result, key=lambda r: r.track_id)


def info(rows: list[genre.native.Observation]) -> dict[int, dict[str, object]]:
    """Mirror local target-availability metadata for synthetic observations."""
    return {
        r.track_id: {
            "human_row_present": True,
            "raw_votes": list(r.votes) if r.votes else None,
            "raw_target_payload": ",".join(r.votes) if r.votes else "",
            "taxonomy_nominated": bool(r.votes),
        }
        for r in rows
    }


class HumanGenreMathTests(unittest.TestCase):
    def test_fractional_bernoulli_math_matches_independent_scalar_calculation(self) -> None:
        rows = [
            observation(1, tags=("genre---jazz",), votes=("jazz", "jazz", "rock")),
            observation(2, tags=("genre---rock",), votes=("rock",) * 3),
        ]
        model = genre.fit(rows, {1: 1, 2: 2})
        priors, theta = [], []
        for name in genre.CLASSES:
            fractions = [(r.votes or ()).count(name) / 3 for r in rows]
            mass = sum(fractions)
            priors.append((1 + mass) / 11)
            theta.append(
                [
                    (1 + sum(y for y, r in zip(fractions, rows, strict=True) if token in r.tags))
                    / (2 + mass)
                    for token in model["vocabulary"]
                ]
            )
        np.testing.assert_allclose(model["prior"], priors, atol=1e-15)
        np.testing.assert_allclose(model["theta"], theta, atol=1e-15)
        query = observation(3, tags=("genre---jazz",))
        unnormalized = []
        for prior, conditional in zip(priors, theta, strict=True):
            value = prior
            for token, chance in zip(model["vocabulary"], conditional, strict=True):
                value *= chance if token in query.tags else 1 - chance
            unnormalized.append(value)
        expected = [p / sum(unnormalized) for p in unnormalized]
        result = genre.predict(model, query)
        np.testing.assert_allclose(result["genre_instrument_nb"], expected, atol=1e-15)
        self.assertAlmostEqual(sum(result["genre_instrument_nb"]), 1)

    def test_component_unit_weights_empty_vocabulary_and_mapping(self) -> None:
        rows = [
            observation(1, artist=7, votes=("jazz",) * 3),
            observation(2, artist=7, votes=("jazz",) * 3),
            observation(3, votes=("rock",) * 3),
        ]
        model = genre.fit(rows, {1: 1, 2: 1, 3: 3})
        self.assertEqual(model["vocabulary"], [])
        self.assertAlmostEqual(model["prior"][5], 2 / 11)
        self.assertAlmostEqual(model["prior"][8], 2 / 11)
        result = genre.predict(
            model,
            observation(
                9, tags=("genre---funk", "genre---soul", "genre---rock", "mood/theme---happy")
            ),
        )
        self.assertEqual(result["genre_instrument_nb"], result["training_human_prior"])
        expected = [0.0] * 9
        expected[4] = expected[8] = 0.5
        self.assertEqual(result["mapped_uploader_genre"], expected)
        self.assertEqual(
            genre.predict(model, observation(9))["mapped_uploader_genre"], model["prior"]
        )

    def test_multiclass_individual_vote_brier_and_log_only_clipping(self) -> None:
        p = np.array([0.5, 0.5, *([0.0] * 7)])
        y = np.array([2 / 3, 1 / 3, *([0.0] * 7)])
        brier, log_loss = genre.losses(p, y)
        self.assertAlmostEqual(float(brier), 0.5)
        self.assertAlmostEqual(float(log_loss), math.log(2))
        hard = np.array([1.0, *([0.0] * 8)])
        self.assertAlmostEqual(float(genre.losses(hard, y)[0]), 2 / 3)
        self.assertAlmostEqual(float(genre.losses(hard, y)[1]), -math.log(genre.CLIP) / 3)
        np.testing.assert_array_equal(hard, [1.0, *([0.0] * 8)])

    def test_full_identity_components_and_training_only_gate_query_label_independence(self) -> None:
        rows = supported_rows()
        identities = genre.cohort(rows)
        support = genre.census_report(rows, identities, info(rows))
        self.assertTrue(all(f["fit_gate"] for f in support["folds"]))
        records, models = genre.predictions(rows, identities, info(rows), support)
        for model in models:
            self.assertTrue(
                all(genre.fold(c) != model["fold"] for c in model["training_components"])
            )
            self.assertEqual(len(model["model"]["prior"]), 9)
        groups = genre.native.components(rows)
        changed = [
            genre.native.Observation(
                *r.identity,
                (*r.tags, "genre---heldout_only")
                if genre.fold(groups[r.track_id]) == 0
                else r.tags,
                None if genre.fold(groups[r.track_id]) == 0 else r.votes,
            )
            for r in rows
        ]
        changed_support = genre.census_report(changed, identities, info(changed))
        changed_records, changed_models = genre.predictions(
            changed, identities, info(changed), changed_support
        )
        self.assertEqual(models[0], changed_models[0])
        self.assertNotIn("genre---heldout_only", models[0]["model"]["vocabulary"])
        self.assertEqual(
            [r["methods"] for r in records if r["fold"] == 0],
            [r["methods"] for r in changed_records if r["fold"] == 0],
        )
        self.assertTrue(
            all(
                not r["scored"] and r["methods"] is not None
                for r in changed_records
                if r["fold"] == 0
            )
        )

    def test_training_support_failure_abstains_all_methods_and_empty_metrics_are_null(self) -> None:
        rows = supported_rows()
        groups = genre.native.components(rows)
        changed = [
            genre.native.Observation(
                *r.identity,
                r.tags,
                None
                if "rock" in (r.votes or ()) and genre.fold(groups[r.track_id]) != 0
                else r.votes,
            )
            for r in rows
        ]
        identities = genre.cohort(changed)
        support = genre.census_report(changed, identities, info(changed))
        self.assertTrue(support["global_support_passes"])
        self.assertTrue(all(not f["fit_gate"] for f in support["folds"]))
        with patch.object(genre, "fit", side_effect=AssertionError("unsupported fit")):
            records, _ = genre.predictions(changed, identities, info(changed), support)
        self.assertTrue(all(r["methods"] is None for r in records))
        result = genre.evaluation(records, support)
        self.assertIsNone(result["scores"]["genre_instrument_nb"]["component_equal_vote_brier"])
        self.assertEqual(result["bootstrap"]["valid_draws"], 0)

    def test_exact_aliases_raw_votes_empty_missing_invalid_disagreement_and_identity_rejection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "human.tsv"
            lines = ["TRACK_ID\tARTIST_ID\tALBUM_ID\tPATH\tDURATION\tANNOTATIONS"]
            values = [
                "",
                "folk_country,funk_soul_rnb,rap_hiphop",
                "Folk_Country,jazz,rock",
                "jazz,rock",
                "folkcountry,jazz,rock",
            ]
            for identity, value in enumerate(values, 1):
                lines.append(
                    f"track_{identity}\tartist_{identity}\talbum_{identity}\t{identity:02d}/{identity}.mp3\t100\tgenre_dortmund---{value}"
                )
            path.write_text("\n".join(lines) + "\n")
            rows, raw, payloads = genre.parse_targets(path)
            self.assertIsNone(rows[0].votes)
            self.assertEqual(payloads[1], "")
            self.assertEqual(raw[2], ("folk_country", "funk_soul_rnb", "rap_hiphop"))
            self.assertEqual(rows[1].votes, ("folkcountry", "funksoulrnb", "raphiphop"))
            self.assertIsNone(genre.vote_reason(rows[1]))
            self.assertEqual(genre.vote_reason(rows[2]), "invalid_vote")
            self.assertEqual(genre.vote_reason(rows[3]), "wrong_vote_count")
            self.assertEqual(genre.vote_reason(rows[4]), "invalid_vote")
            self.assertEqual(raw[5], ("folkcountry", "jazz", "rock"))
            path.write_text(
                path.read_text().replace(
                    "genre_dortmund---\n", "genre_dortmund---\tgenre_dortmund---jazz,jazz,jazz\n"
                )
            )
            with self.assertRaises(ValueError):
                genre.parse_targets(path)
        with self.assertRaises(ValueError):
            genre.native.components([observation(1), observation(1)])
        with self.assertRaises(ValueError):
            genre.native.join([observation(1)], [observation(1, artist=9)])

    def test_new_externally_pinned_local_custody_receipt_paths_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = [b"metadata source bytes", b"human source bytes"]
            specs = []
            for name, content in zip(("metadata.tsv", "human.tsv"), contents, strict=True):
                specs.append(
                    {
                        "path": name,
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "git_blob_sha1": hashlib.sha1(  # noqa: S324 - test Git blob identity.
                            f"blob {len(content)}\0".encode() + content
                        ).hexdigest(),
                    }
                )
                (root / name).write_bytes(content)
            spec = {"source_commit": "fixed", "input_files": specs}
            (root / "protocol.json").write_bytes(genre.encoded(spec))
            protocol_pin = genre.digest(root / "protocol.json")
            receipt = {
                "protocol_sha256": protocol_pin,
                "source_commit": "fixed",
                "success": True,
                "retries": 0,
                "redirects": False,
                "audio_requested": False,
                "total_bytes": sum(map(len, contents)),
                "fresh_capture": True,
                "source_license": "CC-BY-NC-SA-4.0",
                "research_only": True,
                "requests": [
                    {
                        **s,
                        "local_path": str(root / Path(str(s["path"])).name),
                        "url": f"https://raw.githubusercontent.com/MTG/mtg-jamendo-dataset/fixed/{s['path']}",
                        "status": 200,
                        "attempt": 1,
                        "integrity": "pass",
                        "started_utc": "original capture",
                    }
                    for s in specs
                ],
            }
            (root / "receipt.json").write_bytes(genre.encoded(receipt))
            old_pin = genre.digest(root / "receipt.json")
            restored = root / "restored"
            restored.mkdir()
            for content, request in zip(contents, receipt["requests"], strict=True):
                target = restored / Path(str(request["path"])).name
                target.write_bytes(content)
                request["local_path"] = str(target)
            receipt["local_custody_rebinding"] = {
                "parent_receipt_sha256": old_pin,
                "operation": "copied verified bytes; no new network capture",
            }
            (root / "new-receipt.json").write_bytes(genre.encoded(receipt))
            with patch.object(genre, "PROTOCOL_SHA256", protocol_pin):
                self.assertEqual(
                    genre.sources(
                        root / "protocol.json",
                        root / "new-receipt.json",
                        genre.digest(root / "new-receipt.json"),
                    ),
                    (restored / "metadata.tsv", restored / "human.tsv"),
                )
                with self.assertRaises(ValueError):
                    genre.sources(root / "protocol.json", root / "new-receipt.json", old_pin)

    def test_component_equal_scoring_zero_class_support_clipping_and_paired_bootstrap(self) -> None:
        correct = [1.0, *([0.0] * 8)]
        incorrect = [0.0, 1.0, *([0.0] * 7)]
        records = [
            {
                "component_id": component,
                "scored": True,
                "taxonomy_nominated": True,
                "target_reason": None,
                "prediction_reason": None,
                "canonical_votes": ["alternative"] * 3,
                "target": correct,
                "methods": dict.fromkeys(genre.METHODS, probabilities),
            }
            for component, probabilities in ((1, correct), (1, correct), (2, incorrect))
        ]
        report = genre.evaluation(records, {})
        for method in genre.METHODS:
            self.assertAlmostEqual(report["scores"][method]["component_equal_vote_brier"], 1.0)
            self.assertAlmostEqual(report["scores"][method]["track_weighted_vote_brier"], 2 / 3)
            self.assertEqual(
                report["log_loss_clipping"][method], {"positive_target_class_cells": 1, "tracks": 1}
            )
            self.assertIsNone(report["per_class"][1]["component_equal_ovr_vote_brier"][method])
        self.assertEqual(report["bootstrap"]["valid_draws"], 2000)
        for scopes in report["bootstrap"]["comparisons"].values():
            for metrics in scopes.values():
                for value in metrics.values():
                    self.assertEqual(value, {"difference": 0.0, "interval": [0.0, 0.0]})

    def test_whitespace_mutations_fail_physical_census_and_result_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "prepared"
            prepared.mkdir()
            rows = [observation(1)]
            identities = genre.cohort(rows)
            details = info(rows)
            with patch.object(genre, "dataset", return_value=(rows, identities, details)):
                census_pin = genre.census(prepared, "identity-pin", root / "census")
            report = genre.read(root / "census/census.json")
            with (root / "census/census.json").open("ab") as stream:
                stream.write(b" \n")
            with (
                patch.object(genre, "dataset", side_effect=AssertionError("read after tamper")),
                self.assertRaisesRegex(ValueError, "Physical"),
            ):
                genre.load_census(prepared, "identity-pin", root / "census", census_pin)
            with patch.object(
                genre, "load_census", return_value=(rows, identities, details, report)
            ):
                result_pin = genre.evaluate(
                    prepared, "identity-pin", root / "census", census_pin, root / "result"
                )
            with (root / "result/models.json").open("ab") as stream:
                stream.write(b" \n")
            with (
                patch.object(genre, "load_census", side_effect=AssertionError("fit after tamper")),
                self.assertRaisesRegex(ValueError, "Physical"),
            ):
                genre.replay(
                    prepared,
                    "identity-pin",
                    root / "census",
                    census_pin,
                    root / "result",
                    result_pin,
                )

    def test_stage_tamper_resource_and_fresh_output_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            pin = genre.publish(output, {"seal.json": {"research_only": True}}, ())
            self.assertEqual(pin, genre.digest(output / "seal.json"))
            with self.assertRaises(ValueError):
                genre.publish(output, {"seal.json": {}}, ())
            (output / "extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                genre.check_inventory(output, {"seal.json"})
            with patch.object(genre, "MAX_BYTES", 10), self.assertRaises(ValueError):
                genre.publish(root / "large", {"seal.json": {"too_large": "value"}}, ())
