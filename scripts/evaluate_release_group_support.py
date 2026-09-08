"""Emit aggregate-only diagnostics after separate artifact/receipt custody verification."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Final

_EXPECTED_TABLES: Final = frozenset({"direct_anchor", "release_group_support", "typed_evidence"})


class ReleaseGroupSupportEvaluationError(ValueError):
    """Report an incomplete or incompatible local research evidence database."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-release-groups-per-membership", type=int, default=3)
    return parser


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ReleaseGroupSupportEvaluationError("evidence database does not exist")
    connection = sqlite3.connect(f"file:{path.absolute()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _require_completed_database(connection: sqlite3.Connection, max_support: int) -> None:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not tables >= _EXPECTED_TABLES:
        raise ReleaseGroupSupportEvaluationError("evidence database lacks required typed tables")
    if "build_checkpoint" in tables:
        raise ReleaseGroupSupportEvaluationError(
            "evidence database has an active staging checkpoint"
        )
    if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise ReleaseGroupSupportEvaluationError("evidence database fails quick_check")
    historical = connection.execute(
        """SELECT count(*) FROM sqlite_master
           WHERE type IN ('table', 'view') AND lower(name) GLOB '*historical*'"""
    ).fetchone()
    if historical != (0,):
        raise ReleaseGroupSupportEvaluationError("evidence database contains historical inputs")
    cap_violation = connection.execute(
        """SELECT count(*) FROM (
               SELECT genre_id, artist_id, facet, count(*) AS support_count
                 FROM release_group_support
                GROUP BY genre_id, artist_id, facet
               HAVING support_count > ?
           )""",
        (max_support,),
    ).fetchone()
    if cap_violation != (0,):
        raise ReleaseGroupSupportEvaluationError("release-group membership cap is violated")
    typed_support = connection.execute(
        "SELECT count(*) FROM typed_evidence WHERE evidence_kind = 'release_group_support'"
    ).fetchone()
    support = connection.execute("SELECT count(*) FROM release_group_support").fetchone()
    if typed_support != support:
        raise ReleaseGroupSupportEvaluationError(
            "typed support accounting differs from support table"
        )


def evaluate_release_group_support(
    database: Path, *, max_release_groups_per_membership: int = 3
) -> dict[str, object]:
    """Measure aggregate local support; caller separately verifies artifact and receipt custody."""
    if max_release_groups_per_membership < 1:
        raise ReleaseGroupSupportEvaluationError("membership cap must be positive")
    with closing(_read_only(database)) as connection:
        _require_completed_database(connection, max_release_groups_per_membership)
        corroboration = connection.execute(
            """WITH membership AS (
                   SELECT genre_id, artist_id, facet,
                          count(DISTINCT release_group_id) AS support_count
                     FROM release_group_support
                    GROUP BY genre_id, artist_id, facet
               )
               SELECT membership.facet, membership.support_count,
                      count(*) AS support_memberships,
                      sum(EXISTS(
                          SELECT 1 FROM direct_anchor AS direct
                           WHERE direct.genre_id = membership.genre_id
                             AND direct.artist_id = membership.artist_id
                      )) AS direct_corroborated_memberships
                 FROM membership
                GROUP BY membership.facet, membership.support_count
                ORDER BY membership.facet, membership.support_count"""
        ).fetchall()
        independent_corroboration = connection.execute(
            """WITH membership AS (
                   SELECT genre_id, artist_id, count(DISTINCT release_group_id) AS support_count
                     FROM release_group_support
                    GROUP BY genre_id, artist_id
               )
               SELECT membership.support_count,
                      count(*) AS support_memberships,
                      sum(EXISTS(
                          SELECT 1 FROM direct_anchor AS direct
                           WHERE direct.genre_id = membership.genre_id
                             AND direct.artist_id = membership.artist_id
                      )) AS direct_corroborated_memberships
                 FROM membership
                GROUP BY membership.support_count
                ORDER BY membership.support_count"""
        ).fetchall()
        credit_multiplicity = connection.execute(
            """WITH release_group_credit AS (
                   SELECT release_group_id, count(DISTINCT artist_id) AS supported_artist_count
                     FROM release_group_support
                    GROUP BY release_group_id
               )
               SELECT support.facet,
                      CASE
                          WHEN credit.supported_artist_count = 1 THEN '1'
                          WHEN credit.supported_artist_count = 2 THEN '2'
                          ELSE '3_or_more'
                      END AS supported_credit_multiplicity,
                      count(DISTINCT support.release_group_id) AS release_group_count,
                      count(*) AS support_row_count
                 FROM release_group_support AS support
                 JOIN release_group_credit AS credit USING (release_group_id)
                GROUP BY support.facet, supported_credit_multiplicity
                ORDER BY support.facet, supported_credit_multiplicity"""
        ).fetchall()
        typed_counts = connection.execute(
            """SELECT evidence_kind, count(*)
                 FROM typed_evidence
                GROUP BY evidence_kind
                ORDER BY evidence_kind"""
        ).fetchall()
    return {
        "revision": "release-group-support-corroboration-v1",
        "scope": "local_research_only",
        "serving_allowed": False,
        "export_allowed": False,
        "artifact_receipt_binding_verified_by_this_evaluator": False,
        "artifact_receipt_binding_requirement": (
            "Verify the completed artifact database SHA-256, size, and publication receipt "
            "before treating this diagnostic as candidate acceptance."
        ),
        "historical_inputs_present": False,
        "support_count_unit": "distinct_release_groups_per_seed_artist_facet",
        "corroboration_unit": "seed_artist_facet_membership",
        "independent_support_count_unit": "distinct_release_groups_per_seed_artist",
        "corroboration_interpretation": (
            "Direct-claim absence is unknown, not a negative; this observed overlap is not "
            "precision."
        ),
        "credit_multiplicity_note": (
            "Counts only distinct artists receiving matched support in a release group; "
            "it is not the full raw artist-credit cardinality."
        ),
        "typed_evidence_rows": [
            {"evidence_kind": str(kind), "row_count": int(count)} for kind, count in typed_counts
        ],
        "corroboration": [
            {
                "facet": str(facet),
                "distinct_release_group_support": int(support_count),
                "support_membership_count": int(membership_count),
                "direct_corroborated_membership_count": int(corroborated_count),
                "direct_corroboration_rate": round(
                    int(corroborated_count) / int(membership_count), 12
                ),
            }
            for facet, support_count, membership_count, corroborated_count in corroboration
        ],
        "independent_release_group_corroboration": [
            {
                "distinct_release_group_support": int(support_count),
                "support_membership_count": int(membership_count),
                "direct_corroborated_membership_count": int(corroborated_count),
                "direct_corroboration_rate": round(
                    int(corroborated_count) / int(membership_count), 12
                ),
            }
            for support_count, membership_count, corroborated_count in independent_corroboration
        ],
        "matched_supported_credit_multiplicity": [
            {
                "facet": str(facet),
                "supported_credit_multiplicity": str(multiplicity),
                "release_group_count": int(group_count),
                "support_row_count": int(row_count),
            }
            for facet, multiplicity, group_count, row_count in credit_multiplicity
        ],
    }


def main() -> int:
    """Write one compact aggregate report for a completed candidate database."""
    arguments = _parser().parse_args()
    try:
        report = evaluate_release_group_support(
            arguments.database,
            max_release_groups_per_membership=arguments.max_release_groups_per_membership,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, ReleaseGroupSupportEvaluationError, sqlite3.Error) as error:
        sys.stderr.write(f"release-group support evaluation failed: {error}\n")
        return 2
    sys.stdout.write("release-group support evaluation complete\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
