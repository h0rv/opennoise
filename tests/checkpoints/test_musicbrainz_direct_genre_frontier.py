"""Focused boundaries for the local MusicBrainz proper-genre frontier audit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_genre_frontier import (
    DirectGenreFrontierReport,
    DirectGenreMembershipCandidate,
    audit_direct_genre_frontier,
    build_direct_genre_membership_candidate,
    verify_direct_genre_membership_candidate,
)

_SHA = "a" * 64
_ARTIST = "123e4567-e89b-12d3-a456-426614174000"


class DirectGenreFrontierTests(unittest.TestCase):
    """Proper genres, loose tags, and identity abstentions remain separate."""

    def test_counts_only_exact_source_bound_proper_genres(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            layout = _write(
                directory / "layout.json",
                {"output_sha256": _SHA, "unplaced": [{"seed_id": "u1"}, {"seed_id": "u2"}]},
            )
            frontier = _write(
                directory / "frontier.json",
                {
                    "output_sha256": _SHA,
                    "rows": [_frontier_row("u1", 0), _frontier_row("u2", 1)],
                },
            )
            reconciliation = _write(
                directory / "reconciliation.json",
                {
                    "output_sha256": _SHA,
                    "dispositions": [
                        _reconciliation_row("u1", "genre-id"),
                        _reconciliation_row("u2", "other"),
                    ],
                },
            )
            target = _write(
                directory / "target.json",
                {
                    "output_sha256": _SHA,
                    "evidence": [
                        _evidence("u1", facet="genre", target_identity="genre-id"),
                        _evidence("u1", facet="tag", target_identity="tag:example"),
                        _evidence(
                            "u1", facet="genre", target_identity="unreconciled", source_sha="b" * 64
                        ),
                        _evidence(
                            "u1", facet="genre", target_identity="genre-id", match_kind="normalized"
                        ),
                        _evidence("u2", facet="genre", target_identity="other"),
                    ],
                },
            )
            report = audit_direct_genre_frontier(
                layout_path=layout,
                frontier_path=frontier,
                reconciliation_path=reconciliation,
                seed_target_path=target,
            )
        self.assertEqual(report.unplaced_unserved_seed_count, 1)
        self.assertEqual(report.strict_proper_genre_rows, 2)
        self.assertEqual(report.strict_proper_genre_seed_count, 1)
        self.assertEqual(report.identity_eligible_proper_genre_rows, 1)
        self.assertEqual(report.identity_abstained_proper_genre_rows, 1)
        self.assertEqual(
            report.strict_proper_genre_rows,
            report.identity_eligible_proper_genre_rows
            + report.identity_abstained_proper_genre_rows,
        )
        self.assertEqual(report.exact_loose_tag_rows, 1)
        self.assertEqual(report.exact_loose_tag_seed_count, 1)
        self.assertEqual(report.inferred_membership_rows_used, 0)
        self.assertEqual(report.publishable_membership_count, 0)

    def test_identity_conflict_is_not_deduplicated_across_genre_targets(self) -> None:
        report = _report_for_evidence(
            [
                _evidence("u1", facet="genre", target_identity="genre-id"),
                _evidence("u1", facet="genre", target_identity="other-genre"),
            ]
        )
        self.assertEqual(report.strict_proper_genre_rows, 2)
        self.assertEqual(report.identity_eligible_proper_genre_rows, 1)
        self.assertEqual(report.identity_abstained_proper_genre_rows, 1)
        self.assertEqual(
            report.strict_proper_genre_rows,
            report.identity_eligible_proper_genre_rows
            + report.identity_abstained_proper_genre_rows,
        )

    def test_tag_with_a_non_tag_namespace_is_excluded(self) -> None:
        report = _report_for_evidence(
            [
                _evidence(
                    "u1",
                    facet="tag",
                    target_identity="not-a-tag",
                    target_namespace="musicbrainz_genre_id",
                )
            ]
        )
        self.assertEqual(report.exact_loose_tag_rows, 0)
        self.assertEqual(report.exact_loose_tag_seed_count, 0)

    def test_projects_only_reconciled_exact_mbid_proper_genres(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            layout = _write(
                directory / "layout.json", {"output_sha256": _SHA, "unplaced": [{"seed_id": "u1"}]}
            )
            frontier = _write(
                directory / "frontier.json",
                {"output_sha256": _SHA, "rows": [_frontier_row("u1", 0)]},
            )
            reconciliation = _write(
                directory / "reconciliation.json",
                {"output_sha256": _SHA, "dispositions": [_reconciliation_row("u1", "genre-id")]},
            )
            target = _write(
                directory / "target.json",
                {
                    "output_sha256": _SHA,
                    "evidence": [
                        _evidence("u1", facet="genre", target_identity="genre-id"),
                        _evidence("u1", facet="genre", target_identity="other-genre"),
                        _evidence("u1", facet="tag", target_identity="tag:example"),
                    ],
                },
            )
            first = build_direct_genre_membership_candidate(
                layout_path=layout,
                frontier_path=frontier,
                reconciliation_path=reconciliation,
                seed_target_path=target,
            )
            second = build_direct_genre_membership_candidate(
                layout_path=layout,
                frontier_path=frontier,
                reconciliation_path=reconciliation,
                seed_target_path=target,
            )

        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.membership_count, 1)
        self.assertEqual(first.seed_count, 1)
        self.assertEqual(first.artist_mbid_count, 1)
        self.assertEqual(first.memberships[0].musicbrainz_genre_id, "genre-id")
        self.assertFalse(first.historical_assignments_read)
        self.assertFalse(first.alias_or_name_only_bridge_used)
        self.assertFalse(first.public_export_authorized)
        verify_direct_genre_membership_candidate(first)
        malformed = first.model_dump(mode="json")
        malformed["memberships"][0]["artist_mbid"] = "alias:artist"
        with self.assertRaisesRegex(ValueError, "String should match pattern"):
            DirectGenreMembershipCandidate.model_validate_json(json.dumps(malformed))


def _report_for_evidence(evidence: list[dict[str, str]]) -> DirectGenreFrontierReport:
    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        layout = _write(
            directory / "layout.json", {"output_sha256": _SHA, "unplaced": [{"seed_id": "u1"}]}
        )
        frontier = _write(
            directory / "frontier.json", {"output_sha256": _SHA, "rows": [_frontier_row("u1", 0)]}
        )
        reconciliation = _write(
            directory / "reconciliation.json",
            {"output_sha256": _SHA, "dispositions": [_reconciliation_row("u1", "genre-id")]},
        )
        target = _write(directory / "target.json", {"output_sha256": _SHA, "evidence": evidence})
        return audit_direct_genre_frontier(
            layout_path=layout,
            frontier_path=frontier,
            reconciliation_path=reconciliation,
            seed_target_path=target,
        )


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _frontier_row(seed_id: str, served: int) -> dict[str, object]:
    return {
        "source_item_id": seed_id,
        "observed_artists": {"wikidata_p136": served},
        "reconciliation_disposition": "musicbrainz_only",
    }


def _reconciliation_row(seed_id: str, genre_id: str) -> dict[str, object]:
    return {
        "source_item_id": seed_id,
        "musicbrainz_identities": [{"namespace": "musicbrainz_genre_id", "identifier": genre_id}],
    }


def _evidence(  # noqa: PLR0913
    seed_id: str,
    *,
    facet: str,
    target_identity: str,
    match_kind: str = "exact",
    source_sha: str = _SHA,
    target_namespace: str | None = None,
) -> dict[str, str]:
    return {
        "seed_source_item_id": seed_id,
        "seed_name": "example",
        "artist_id": _ARTIST,
        "facet": facet,
        "match_kind": match_kind,
        "target_identity": target_identity,
        "target_name": "example",
        "target_namespace": target_namespace
        or ("musicbrainz_genre_id" if facet == "genre" else "musicbrainz_tag_name"),
        "source_record_id": f"musicbrainz:artist:{_ARTIST}",
        "source_record_sha256": source_sha,
    }
