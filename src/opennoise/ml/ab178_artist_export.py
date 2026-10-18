"""Exact-credit artist evidence from frozen recording inference, without genre inference."""

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from opennoise.ml import ab178_portable as portable

MAX_CREDITS = 16
MAX_ARTISTS = 1000
ROLES = ("heldout", "fit_member", "training_not_fitted", "unresolved_identity")


def query_role(row: dict[str, Any], heldout_fold: int, *, verified_identity: bool) -> str:
    """Separate fitted observations, heldout queries and unresolved identities."""
    if not verified_identity or row["fold"] is None:
        return "unresolved_identity"
    if row["fit_member"]:
        return "fit_member"
    return "heldout" if row["fold"] == heldout_fold else "training_not_fitted"


def aggregate(  # noqa: C901 - retain recording-to-credit evidence assembly in one boundary.
    body: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Group recording observations by every verified credit, never by selection association."""
    roster = {row["recording_mbid"]: row for row in body["roster"]}
    artists: dict[str, Any] = {}
    for row in roster.values():
        artist_ids = row["credited_artist_mbids"] or []
        if len(artist_ids) > MAX_CREDITS:
            raise ValueError("Artist export credit bound exceeded")
        for artist in artist_ids:
            artists.setdefault(
                artist,
                {
                    "recording_mbids": [],
                    "outcome_counts": Counter(),
                    "neighbors": {role: {} for role in ROLES},
                },
            )
    if len(artists) > MAX_ARTISTS:
        raise ValueError("Artist export artist bound exceeded")
    records = []
    for row in result["rows"]:
        identity = row["recording_mbid"]
        artist_ids = roster[identity]["credited_artist_mbids"] or []
        role = query_role(
            row,
            body["frame"]["heldout_fold"],
            verified_identity=bool(artist_ids)
            and roster[identity]["evidence"]["identity_state"] == "matched",
        )
        records.append(
            {
                **{k: v for k, v in row.items() if k != "vector"},
                "credited_artist_mbids": artist_ids,
                "query_role": role,
            }
        )
        for artist in artist_ids:
            entry = artists[artist]
            entry["recording_mbids"].append(identity)
            entry["outcome_counts"][row["outcome"]] += 1
            for neighbor in row["neighbors"]:
                candidate = neighbor["recording_mbid"]
                for credited in roster[candidate]["credited_artist_mbids"] or []:
                    if credited == artist:
                        continue
                    evidence = entry["neighbors"][role].setdefault(credited, [])
                    evidence.append(
                        {
                            "query_recording_mbid": identity,
                            "candidate_recording_mbid": candidate,
                            "distance": neighbor["distance"],
                        }
                    )
    exported = []
    for artist, entry in sorted(artists.items()):
        exported.append(
            {
                "artist_mbid": artist,
                "recording_mbids": sorted(entry["recording_mbids"]),
                "outcome_counts": dict(sorted(entry["outcome_counts"].items())),
                "neighbor_evidence": {
                    role: [
                        {
                            "artist_mbid": candidate,
                            "query_recording_count": len(
                                {r["query_recording_mbid"] for r in evidence}
                            ),
                            "recording_pair_count": len(evidence),
                            "observations": evidence,
                        }
                        for candidate, evidence in sorted(entry["neighbors"][role].items())
                    ]
                    for role in ROLES
                },
            }
        )
    return {
        "artists": exported,
        "recordings": records,
        "counts": {
            "nominated_recordings": len(records),
            "verified_credited_artists": len(artists),
            "recordings_without_verified_credits": sum(
                not row["credited_artist_mbids"] for row in records
            ),
            "recording_outcomes": dict(sorted(Counter(row["outcome"] for row in records).items())),
            "emitted_by_query_role": {
                role: sum(
                    row["outcome"] == "emitted" and row["query_role"] == role for row in records
                )
                for role in ROLES
            },
        },
    }


def export_artists(
    source: Path, source_pin: str, bundle: Path, bundle_pin: str, output: Path
) -> str:
    """Replay native identities/features, infer all nominations and publish one JSON export."""
    portable.destination(output, (source, bundle))
    body = portable.bundle(bundle, bundle_pin)
    identities = [row["recording_mbid"] for row in body["roster"]]
    with TemporaryDirectory(prefix="opennoise-artist-export-") as temporary:
        queries = Path(temporary) / "queries"
        query_pin = portable.export_queries(
            bundle, bundle_pin, source, source_pin, identities, queries
        )
        result = portable.infer(bundle, bundle_pin, queries, query_pin)
    report = {
        "revision": "native-ab178-artist-evidence-v1",
        "bundle_sha256": bundle_pin,
        "source_receipt_sha256": source_pin,
        "query_sha256": query_pin,
        "inference_sha256": portable.hash_value(result),
        "producer_sha256": portable.bank.digest(Path(__file__)),
        "scope": {
            "evidence": "recording-neighbor observations grouped by exact core artist credits",
            "musical_relevance_established": False,
            "artist_similarity_score": False,
            "genre_state": "unsupported_by_ab178_model",
            "genre_memberships": [],
            "credit_policy": "all verified co-credits; observations may repeat across artists",
            "denominator": "nominated recordings only; unknown credits remain unassigned",
            "license": "CC0-1.0 native AcousticBrainz and MusicBrainz core metadata",
        },
        **aggregate(body, result),
    }
    return portable.publish(output, "artists.json", report)
