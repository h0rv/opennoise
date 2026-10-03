"""Source closure and pagination failures cannot become complete catalog claims."""

import copy
import json
import unittest
from typing import Any

from opennoise.serving.metadata.full_recording_catalog import (
    artist_summary,
    project_page,
    request_plan,
    verify_ledger_order,
)

ARTIST = "11111111-1111-4111-8111-111111111111"
RECORDING = "22222222-2222-4222-8222-222222222222"


class CatalogClosureTests(unittest.TestCase):
    def plan(self, count: int = 1) -> dict[str, Any]:
        return request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": count}]},
        )

    def body(
        self, count: int = 1, rows: list[dict[str, Any]] | None = None, offset: int = 0
    ) -> bytes:
        if rows is None:
            rows = [
                {
                    "id": RECORDING,
                    "title": "Source title",
                    "artist-credit": [{"artist": {"id": ARTIST, "name": "Artist"}}],
                }
            ]
        return json.dumps(
            {"recording-count": count, "recording-offset": offset, "recordings": rows}
        ).encode()

    def test_complete_requires_closing_native_probe(self) -> None:
        requests = self.plan()["requests"]
        pages = [project_page(self.body(), r) for r in requests]
        self.assertEqual(
            artist_summary(ARTIST, requests, pages)["status"], "observed_window_complete"
        )
        self.assertEqual(artist_summary(ARTIST, requests, [pages[0], None])["status"], "partial")

    def test_zero_count_is_probed_and_closed(self) -> None:
        requests = self.plan(0)["requests"]
        self.assertEqual([r["stage"] for r in requests], ["initial", "closing"])
        pages = [project_page(self.body(0, []), r) for r in requests]
        self.assertEqual(
            artist_summary(ARTIST, requests, pages)["status"], "observed_window_complete"
        )

    def test_native_count_drift_is_inconsistent(self) -> None:
        requests = self.plan()["requests"]
        pages = [project_page(self.body(), requests[0]), project_page(self.body(2), requests[1])]
        self.assertEqual(artist_summary(ARTIST, requests, pages)["status"], "inconsistent")

    def test_same_count_changed_first_page_is_inconsistent(self) -> None:
        requests = self.plan()["requests"]
        first = project_page(self.body(), requests[0])
        changed = self.body().replace(b"Source title", b"Changed title")
        self.assertEqual(
            artist_summary(ARTIST, requests, [first, project_page(changed, requests[1])])["status"],
            "inconsistent",
        )

    def test_credit_mismatch_or_mixed_field_remains_custody_only(self) -> None:
        request = self.plan()["requests"][0]
        for bad in [
            self.body().replace(ARTIST.encode(), RECORDING.encode()),
            self.body().replace(b'"title":', b'"genres": [], "title":'),
        ]:
            page = project_page(bad, request)
            self.assertEqual(page["field_scope"], "raw_custody_only")
            self.assertEqual(page["facts"], [])
            self.assertEqual(len(page["rejected_rows"]), 1)

    def test_missing_id_is_explicit_unapproved_row(self) -> None:
        page = project_page(
            self.body(rows=[{"title": "Missing identity"}]), self.plan()["requests"][0]
        )
        self.assertEqual(page["rejected_rows"][0]["row_index"], 0)

    def test_offset_or_cardinality_tamper_rejected(self) -> None:
        request = self.plan()["requests"][0]
        for body in [self.body(offset=100), self.body(0)]:
            with self.assertRaises(ValueError):
                project_page(body, request)

    def test_duplicate_native_recording_never_complete(self) -> None:
        requests = self.plan(2)["requests"]
        rows = json.loads(self.body())["recordings"] * 2
        pages = [project_page(self.body(2, rows), r) for r in requests]
        summary = artist_summary(ARTIST, requests, pages)
        self.assertEqual(summary["duplicate_recording_rows"], 1)
        self.assertEqual(summary["status"], "partial")

    def test_all_unknown_preserves_denominator(self) -> None:
        requests = self.plan(201)["requests"]
        summary = artist_summary(ARTIST, requests, [None] * len(requests))
        self.assertEqual(summary["status"], "unknown")
        self.assertEqual(summary["unfetched_baseline_count"], 201)

    def test_extra_unknown_stage_order_and_after_stop_rejected(self) -> None:
        plan = self.plan()
        captures: list[dict[str, Any]] = [
            {
                "request": r,
                "actual_request": True,
                "custody": {"decoded_bytes": 1, "complete_body": True},
                "status_code": 500,
                "projection": None,
                "fetched_at": "2026-10-03T00:00:00+00:00",
                "headers": {},
                "header_scope": {
                    "approved": True,
                    "omitted_count": 0,
                    "omitted_names": [],
                    "omitted_names_truncated": False,
                    "oversized_or_duplicate_names": [],
                },
                "outcome": "http_status",
                "started_monotonic_seconds": n * 1.2,
            }
            for n, r in enumerate(plan["requests"])
        ]
        verify_ledger_order(plan, captures)
        for mutate in ["stage", "extra", "order", "stop", "spacing"]:
            bad = copy.deepcopy(captures)
            if mutate == "stage":
                bad[0]["request"]["stage"] = "unknown"
            elif mutate == "extra":
                bad.append(copy.deepcopy(bad[-1]))
            elif mutate == "order":
                bad.reverse()
            elif mutate == "spacing":
                bad[1]["started_monotonic_seconds"] = 0.5
            else:
                bad[0].update(
                    outcome="cgroup_capacity_unknown",
                    actual_request=False,
                    custody=None,
                    status_code=None,
                    fetched_at=None,
                    started_monotonic_seconds=None,
                )
            with self.assertRaises(ValueError):
                verify_ledger_order(plan, bad)

    def test_policy_tamper_rejected(self) -> None:
        plan = copy.deepcopy(self.plan())
        plan["limits"]["requests"] += 1
        with self.assertRaises(ValueError):
            verify_ledger_order(plan, [])


if __name__ == "__main__":
    unittest.main()
