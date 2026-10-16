"""Synthetic pilot contracts; no ratings or real audio are created by these tests."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.deployment import fma_listening_pilot as pilot


def queries() -> list[dict]:
    """Six fictitious queries with disjoint illustrative candidates."""
    return [
        {"track_id": i, "component_id": i, "raw": 20 + i, "simple": 30 + i, "reason": None}
        for i in range(1, 7)
    ]


def structures() -> tuple[dict, dict]:
    """Build synthetic neutral slot metadata and its private key."""
    items, key = pilot.assignments(queries())
    packets = {
        s: {"revision": pilot.REVISION, "slot": int(s), "items": rows} for s, rows in items.items()
    }
    return {
        "key": key,
        "packet_sha256": {s: pilot.sha(json.dumps(p).encode()) for s, p in packets.items()},
    }, packets


def answers(packet: dict, pin: str) -> dict:
    """Construct an entirely unanswered synthetic response."""
    return {
        "revision": pilot.REVISION,
        "packet_sha256": pin,
        "slot": packet["slot"],
        "items": [
            {
                "item_id": r["item_id"],
                "choice": None,
                "heard_query": None,
                "heard_A": None,
                "heard_B": None,
                "familiarity": None,
                "conflict": None,
                "notes": "",
            }
            for r in packet["items"]
        ],
    }


class ListeningPilotTests(TestCase):
    def test_counterbalance_exact_and_input_order_independent(self) -> None:
        items, key = pilot.assignments(queries())
        self.assertEqual((items, key), pilot.assignments(list(reversed(queries()))))
        self.assertEqual(sum(r["A"] == "raw" for r in key["1"].values()), 3)
        shifted = queries()
        for row in shifted:
            row["track_id"] += 100
        _, other_key = pilot.assignments(shifted)
        self.assertNotEqual(
            {i for i, r in key["1"].items() if r["A"] == "raw"},
            {i for i, r in other_key["1"].items() if r["A"] == "raw"},
        )
        for identity in key["1"]:
            self.assertEqual(key["1"][identity]["A"], key["2"][identity]["B"])
            self.assertEqual(key["1"][identity]["query"], key["2"][identity]["query"])
        for packet in items.values():
            self.assertNotIn('"raw"', json.dumps(packet))
            self.assertNotIn('"simple"', json.dumps(packet))
        duplicate = queries()
        duplicate[1] = duplicate[0]
        with self.assertRaises(ValueError):
            pilot.assignments(duplicate)

    def test_all_missing_twelve_denominator_and_per_query_cluster(self) -> None:
        coordinator, packets = structures()
        result = pilot.summarize(coordinator, packets, [])
        self.assertEqual(result["outcome_counts"]["missing"], 12)
        self.assertEqual(result["query_components"], 6)
        self.assertEqual(len(result["queries"]), 6)
        self.assertFalse(result["distinct_participants_confirmed"])
        self.assertFalse(result["musical_quality_validated"])

    def test_real_choices_preserved_with_exclusions_and_disagreement(self) -> None:
        coordinator, packets = structures()
        responses = [answers(packets[s], coordinator["packet_sha256"][s]) for s in ("1", "2")]
        for result in responses:
            for row in result["items"]:
                row.update(choice="A", heard_query=True, heard_A=True, heard_B=True, conflict=False)
        summary = pilot.summarize(
            coordinator, packets, responses, distinct_participants_confirmed=True
        )
        self.assertEqual(summary["outcome_counts"]["A"], 12)
        self.assertEqual(summary["eligible_outcome_counts"], {"raw": 6, "simple": 6})
        self.assertTrue(all(r["disagreement"] for r in summary["queries"]))
        responses[0]["items"][0]["heard_B"] = False
        altered = pilot.summarize(coordinator, packets, responses)
        self.assertEqual(altered["outcome_counts"]["A"], 12)
        self.assertEqual(sum(altered["eligible_outcome_counts"].values()), 11)
        self.assertTrue(
            any(
                "incomplete_listening_self_report" in r["exclusions"]
                for q in altered["queries"]
                for r in q["observations"]
            )
        )

    def test_unknown_conflict_is_retained_not_filled_or_counted_as_preference(self) -> None:
        coordinator, packets = structures()
        value = answers(packets["1"], coordinator["packet_sha256"]["1"])
        row = value["items"][0]
        row.update(choice="A", heard_query=True, heard_A=True, heard_B=True, conflict=None)
        result = pilot.summarize(coordinator, packets, [value])
        self.assertEqual(result["outcome_counts"]["A"], 1)
        self.assertEqual(result["eligible_outcome_counts"], {})
        observed = next(q for q in result["queries"] if q["item_id"] == row["item_id"])[
            "observations"
        ][0]
        self.assertIsNone(observed["response"]["conflict"])
        self.assertIn("conflict_or_unreported_conflict", observed["exclusions"])

    def test_identical_unsupported_and_all_nonpreferences_retained(self) -> None:
        source = queries()
        source[0]["simple"] = source[0]["raw"]
        source[1]["raw"] = None
        source[1]["reason"] = "out_of_support"
        items, key = pilot.assignments(source)
        packets = {
            s: {"revision": pilot.REVISION, "slot": int(s), "items": rows}
            for s, rows in items.items()
        }
        coordinator = {"key": key, "packet_sha256": {"1": "p1", "2": "p2"}}
        result = answers(packets["1"], "p1")
        for row, choice in zip(
            result["items"], ["tie", "neither", "unsure", "playback_failure", "A", "B"], strict=True
        ):
            row.update(choice=choice, heard_query=True, heard_A=True, heard_B=True, conflict=False)
        summary = pilot.summarize(coordinator, packets, [result])
        self.assertEqual(
            summary["outcome_counts"],
            {
                "missing": 6,
                "A": 1,
                "B": 1,
                "tie": 1,
                "neither": 1,
                "unsure": 1,
                "playback_failure": 1,
            },
        )
        excluded = [
            reason
            for q in summary["queries"]
            for r in q["observations"]
            for reason in r["exclusions"]
        ]
        self.assertIn("identical_candidates", excluded)
        self.assertIn("unsupported", excluded)

    def test_response_pin_duplicate_unknown_and_denominator_reject(self) -> None:
        coordinator, packets = structures()
        valid = answers(packets["1"], coordinator["packet_sha256"]["1"])
        for change in ("pin", "duplicate", "unknown", "short", "extra", "bad_choice", "bad_bool"):
            value = copy.deepcopy(valid)
            if change == "pin":
                value["packet_sha256"] = "changed"
            elif change == "duplicate":
                value["items"][1] = value["items"][0]
            elif change == "unknown":
                value["items"][0]["item_id"] = "UNKNOWN"
            elif change == "short":
                value["items"].pop()
            elif change == "extra":
                value["items"][0]["method"] = "raw"
            elif change == "bad_choice":
                value["items"][0]["choice"] = []
            else:
                value["items"][0]["heard_A"] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                pilot.response(packets["1"], coordinator["packet_sha256"]["1"], value)
        with self.assertRaises(ValueError):
            pilot.summarize(coordinator, packets, [valid, valid])

    def test_synthetic_sealed_build_closed_inventory_and_summary(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            candidate, baseline = root / "candidate", root / "baseline"
            (candidate / "audio").mkdir(parents=True)
            baseline.mkdir()
            tracks = []
            for identity in range(1, 56):
                body = f"FAKE AUDIO fixture {identity}".encode()
                (candidate / "audio" / f"{identity}.mp3").write_bytes(body)
                row = dict.fromkeys(pilot.CREDIT_FIELDS, "")
                row.update(
                    track_id=identity,
                    artist_id=identity,
                    audio_path=f"audio/{identity}.mp3",
                    audio_sha256=pilot.sha(body),
                    audio_bytes=len(body),
                    duration_seconds=1,
                    title=f"Synthetic {identity}",
                    artist_name="Fixture",
                    attribution="Not real music",
                    genre_ids=[1],
                    embedded_notices={},
                    embedded_source_urls=[],
                    embedded_curators=[],
                    embedded_extra_text_present=False,
                )
                tracks.append(row)
            manifest = {
                "tracks": tracks,
                "metadata_attribution": "Synthetic test; not FMA metadata",
            }
            (candidate / "manifest.json").write_text(json.dumps(manifest))
            evaluation = {
                "queries": [
                    {
                        "track_id": r["track_id"],
                        "component_id": r["component_id"],
                        "fold": 2,
                        "reason": None,
                        "arms": {
                            "raw": {"ranking": [r["raw"]]},
                            "simple4": {"ranking": [r["simple"]]},
                        },
                    }
                    for r in queries()
                ]
            }
            (baseline / "evaluation.json").write_text(json.dumps(evaluation))
            design = root / "design.json"
            design.write_text("synthetic test protocol")
            seal = root / "seal.json"
            output = root / "pilot"
            with (
                patch.object(pilot, "_candidate", return_value=manifest),
                patch.object(pilot, "_evaluations", return_value=evaluation),
                patch.object(pilot, "DESIGN_SHA256", pilot.sha(design.read_bytes())),
            ):
                pilot.freeze_pilot(candidate, baseline, "baseline-test-pin", design, seal)
                with self.assertRaises(ValueError):
                    pilot.build_pilot(candidate, baseline, seal, "bad", output)
                self.assertFalse(output.exists())
                result = pilot.build_pilot(
                    candidate, baseline, seal, pilot.sha(seal.read_bytes()), output
                )
                for slot in ("1", "2"):
                    packet = pilot.validate_packet(
                        output / f"listener-{slot}", result["inventory_sha256"][slot]
                    )
                    self.assertNotIn('"raw"', json.dumps(packet))
                    self.assertNotIn('"simple"', json.dumps(packet))
                    self.assertTrue(all("genre_ids" not in r for r in packet["tracks"].values()))
                mapping = output / "coordinator" / "mapping.json"
                summary = pilot.summarize_files(
                    output, pilot.sha(mapping.read_bytes()), [], root / "summary.json"
                )
                self.assertEqual(summary["outcome_counts"]["missing"], 12)
                (output / "listener-1" / "key.json").write_text("should never be served")
                with self.assertRaises(ValueError):
                    pilot.validate_packet(output / "listener-1", result["inventory_sha256"]["1"])
