"""Build a frozen, method-blind independent musical review packet.

The input is the selected-cohort artists/data.json portable projection. It is
used only as a roster and exact-credit evidence index; it supplies no musical
judgments. The builder never fills reviewer identities or ratings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

SEED = 20261003
SAMPLE_SIZE = 60
DENOMINATOR_SIZE = 150


def sha(path: Path) -> str:
    """Hash a source or packet file without loading the file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_volume(artist: dict[str, Any]) -> int:
    """Count supplied claims, credited recordings and literal links."""
    return (
        len(artist.get("claims", []))
        + len(artist.get("recordings", []))
        + len(artist.get("links", []))
    )


def build(
    source: Path, out: Path, provider_destinations_path: Path | None = None
) -> dict[str, Any]:
    """Freeze a method-blind artist packet without entering listener judgments."""
    raw = json.loads(source.read_text(encoding="utf-8"))
    provider_map: dict[str, dict[str, Any]] = {}
    if provider_destinations_path:
        destinations = json.loads(provider_destinations_path.read_text(encoding="utf-8"))
        provider_map = {r["recording_mbid"]: r for r in destinations["recordings"]}
    artists = sorted(raw["artists"], key=lambda a: a["artist_mbid"])
    if len(artists) != DENOMINATOR_SIZE or len({a["artist_mbid"] for a in artists}) != len(artists):
        raise ValueError("Expected the frozen 150-artist selected-cohort denominator")
    selected, volume, cuts, band = _sample_artists(artists)
    selected_ids = {a["artist_mbid"] for a in selected}
    cohort, source_key, assignments = _review_rows(selected, provider_map, volume, band)
    # Method comparison tasks stay sealed: these rows receive actual candidate
    # suggestions only after the selected model outputs are frozen by the parent.
    pair_tasks = [
        {
            "pair_item_id": f"N{i:03d}",
            "query_item_id": row["item_id"],
            "candidate_a": "",
            "candidate_b": "",
            "popularity_baseline": "",
            "assignment_key_ref": "sealed/method-key.json",
        }
        for i, row in enumerate(cohort, 1)
    ]
    declaration = _declaration(
        raw, source, provider_destinations_path, (len(artists), len(cohort)), cuts
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "declaration.json").write_text(
        json.dumps(declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "cohort.json").write_text(
        json.dumps(
            {
                "artists": cohort,
                "denominator_count": len(artists),
                "sample_count": len(cohort),
                "excluded_denominator_ids": sorted(
                    {a["artist_mbid"] for a in artists} - selected_ids
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "reviewer_assignments.json").write_text(
        json.dumps(assignments, indent=2) + "\n", encoding="utf-8"
    )
    coordinator = out.parent / (out.name + "-coordinator")
    coordinator.mkdir(parents=True, exist_ok=True)
    (coordinator / "selected150-source-key.json").write_text(
        json.dumps(
            {
                "warning": (
                    "Coordinator-only. Hide from listeners until judgment collection is complete."
                ),
                "items": source_key,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (coordinator / "sealed-method-assignment-key.template.json").write_text(
        json.dumps(
            {
                "warning": (
                    "Coordinator-only. Populate after candidate outputs are frozen; never "
                    "distribute with reviewer packet."
                ),
                "methods": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_artist_forms(out, cohort, pair_tasks)
    _write_recording_forms(out, artists, provider_map)
    _write_packet_instructions(out, coordinator)
    return {
        "denominator": len(artists),
        "sample": len(cohort),
        "recording_items": sum(len(a["exact_recordings"]) for a in cohort),
        "strata": dict(
            Counter(
                f"{band(a)}|{'observed' if a.get('direct_genres') else 'missing'}" for a in artists
            )
        ),
    }


def _sample_artists(
    artists: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int], tuple[int, int], Callable[[dict[str, Any]], str]]:
    """Sample artists."""
    volume = {a["artist_mbid"]: evidence_volume(a) for a in artists}
    ranked = sorted(volume.values())
    cuts = (ranked[len(ranked) // 3], ranked[(2 * len(ranked)) // 3])

    def band(a: dict[str, Any]) -> str:
        n = volume[a["artist_mbid"]]
        return "low" if n <= cuts[0] else "medium" if n <= cuts[1] else "high"

    # Proportional, deterministic allocation across evidence-volume x direct-genre
    # presence strata; each cell retains its actual denominator and unknowns.
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for a in artists:
        cell = (band(a), "observed" if a.get("direct_genres") else "missing")
        cells.setdefault(cell, []).append(a)
    rng = random.Random(SEED)  # noqa: S311 - reproducible sampling.
    for values in cells.values():
        values.sort(key=lambda a: a["artist_mbid"])
        rng.shuffle(values)
    selected: list[dict[str, Any]] = []
    allocations: dict[str, int] = {}
    # Round-robin cells avoids allowing the largest evidence stratum to consume
    # the sample. Empty and undersized cells remain explicitly reported.
    while len(selected) < min(SAMPLE_SIZE, len(artists)):
        progressed = False
        for cell in sorted(cells):
            index = allocations.get("|".join(cell), 0)
            values = cells[cell]
            if index < len(values) and len(selected) < SAMPLE_SIZE:
                selected.append(values[index])
                allocations["|".join(cell)] = index + 1
                progressed = True
        if not progressed:
            break
    # Preserve an independent random presentation order, independent of strata.
    rng.shuffle(selected)
    return selected, volume, cuts, band


def _review_rows(
    selected: list[dict[str, Any]],
    provider_map: dict[str, dict[str, Any]],
    volume: dict[str, int],
    band: Callable[[dict[str, Any]], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Review rows."""
    cohort: list[dict[str, Any]] = []
    source_key: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for i, a in enumerate(selected, 1):
        aid = a["artist_mbid"]
        recs = sorted(a.get("recordings", []), key=lambda r: r["recording_mbid"])
        row = {
            "item_id": f"M{i:03d}",
            "artist_mbid": aid,
            "artist_name": a["name"],
            "artist_url": f"https://musicbrainz.org/artist/{aid}",
            "region": "unknown",
            "language": "unknown",
            "era": "unknown",
            "exact_recordings": [
                {
                    "recording_mbid": r["recording_mbid"],
                    "title": r["title"],
                    "recording_url": r["url"],
                    "credited_artist_mbids": r["credited_artist_mbids"],
                    "credit_verified": r.get("verification"),
                    "provider": "",
                    "provider_destinations": provider_map.get(r["recording_mbid"], {}).get(
                        "destinations", []
                    ),
                    "availability_status": "destination_unlisted"
                    if not provider_map.get(r["recording_mbid"], {}).get("destinations")
                    else "destination_found_availability_not_checked",
                }
                for r in recs
            ],
            "listening_access_status": "not_checked",
        }
        cohort.append(row)
        source_key.append(
            {
                "item_id": row["item_id"],
                "direct_genre_ids": list(a.get("direct_genres", [])),
                "evidence_volume": volume[aid],
                "evidence_volume_stratum": band(a),
                "cohort_sources": a.get("cohort_sources", []),
            }
        )
        # Two independent reviewers are required for each unit. Reviewer IDs
        # intentionally blank; coordinators assign people without inventing them.
        assignments.extend(
            {
                "item_id": row["item_id"],
                "reviewer_slot": reviewer_slot,
                "reviewer_id": "",
                "status": "unassigned",
            }
            for reviewer_slot in (1, 2)
        )

    return cohort, source_key, assignments


def _declaration(
    raw: dict[str, Any],
    source: Path,
    provider_destinations_path: Path | None,
    counts: tuple[int, int],
    cuts: tuple[int, int],
) -> dict[str, Any]:
    """Freeze the declared sampling and judgment protocol."""
    denominator_count, sample_count = counts
    attribution = raw.get("attribution", {})
    attribution_scope = (
        attribution.get("scope", "portable selected cohort")
        if isinstance(attribution, dict)
        else str(attribution)
    )
    return {
        "revision": "independent-musical-review-packet-v1",
        "frozen_at": "2026-10-03",
        "scope": (
            "selected-150-artist open-build review cohort; does not certify global "
            "coverage or legacy parity"
        ),
        "denominator": {
            "count": denominator_count,
            "source": str(source),
            "sha256": sha(source),
            "selection_scope": attribution_scope,
        },
        "provider_destination_receipt": (
            {
                "path": str(provider_destinations_path),
                "sha256": sha(provider_destinations_path),
                "scope": (
                    "exact MusicBrainz recording IDs mapped to literal provider "
                    "destinations; availability and listening permission not checked"
                ),
            }
            if provider_destinations_path
            else None
        ),
        "sampling": {
            "seed": SEED,
            "algorithm": (
                "Python random.Random; round-robin across evidence-volume tercile x "
                "direct-genre observed/missing; shuffled presentation"
            ),
            "sample_size": sample_count,
            "evidence_volume": (
                "count of direct claims, exact credited recordings, and outbound links "
                "in source projection"
            ),
            "thresholds": {
                "volume_tercile_cutpoints_inclusive": list(cuts),
                "direct_genre": "source projection has at least one direct genre identifier",
            },
            "regions_languages_eras": (
                "unknown retained because source roster has no such observations; no "
                "geographic or linguistic representativeness claim"
            ),
        },
        "review_design": {
            "independent_reviewers_per_item": 2,
            "reviewer_conflicts_required": True,
            "method_blinding": (
                "candidate methods use randomized A/B labels; assignment key withheld "
                "during judgments"
            ),
            "historical_memberships_hidden": True,
            "source_votes_hidden": True,
            "confidence_hidden": True,
            "unsure_and_access_failure_retained": True,
            "adjudication": "retain both original judgments; adjudication is a separate record",
        },
        "rater_scale": {
            "fit_1_5": {
                "1": "does not fit",
                "2": "mostly does not fit",
                "3": "mixed or uncertain fit",
                "4": "good fit",
                "5": "very strong fit",
            },
            "confidence_1_5": {
                "1": "very unsure",
                "2": "low confidence",
                "3": "moderate confidence",
                "4": "high confidence",
                "5": "very high confidence",
            },
            "familiarity_0_4": {
                "0": "not familiar",
                "1": "heard a little",
                "2": "some familiarity",
                "3": "very familiar",
                "4": "expert or close familiarity",
            },
        },
        "frozen_decision_thresholds": {
            "independent_item_coding": (
                "unanimous fit-positive only when both reviewers rate >=4 and neither "
                "abstains; unanimous fit-negative only when both rate <=2; all other "
                "responses stay mixed/indeterminate with both rows preserved"
            ),
            "membership": (
                "report fit at broad/subgenre/micro scope and confidence; use this "
                "cohort only for calibration/development, then freeze any score "
                "threshold before a disjoint confirmation cohort"
            ),
            "neighbors": (
                "record cultural and sonic relevance separately; method preference is "
                "supported only by an explicit reviewer choice, while ties, neither, "
                "unsure and unsupported stay separate; no aggregate promotion "
                "threshold before confirmation"
            ),
            "recordings": (
                "separate fit and diversity from popularity; unavailable is not a "
                "negative quality rating"
            ),
            "maps": (
                "judge neighborhood utility separately from layout and retain "
                "unpositioned alternatives"
            ),
            "listening": (
                "require exact recording identity plus per-track license, permitted "
                "provider URL and region/date access status"
            ),
        },
        "limitations": [
            (
                "The roster is a selected 150-artist engineering cohort, not a sample "
                "of world music."
            ),
            ("Region, language and era are unknown for every roster item and remain explicit."),
            (
                "Only exact credited recording evidence present in the frozen "
                "projection is attached; absence means no cohort recording was "
                "supplied, not absence from an artist's discography."
            ),
            ("Listening provider permission and current availability have not been verified."),
            "No reviewer identities, judgments, or access outcomes are populated.",
        ],
    }


def _write_artist_forms(
    out: Path, cohort: list[dict[str, Any]], pair_tasks: list[dict[str, Any]]
) -> None:
    """Write artist forms."""
    with (out / "membership-form.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "item_id",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "candidate_label_display",
                "scope_broad_sub_micro",
                "fit_1_5",
                "confidence_1_5",
                "evidence_recording_mbids",
                "unsure",
                "unsupported",
                "access_failure",
                "notes",
            ],
        )
        w.writeheader()
        for row in cohort:
            for slot in (1, 2):
                w.writerow(
                    {
                        "item_id": row["item_id"],
                        "reviewer_slot": slot,
                        "reviewer_id": "",
                        "familiarity_0_4": "",
                        "conflict_description": "",
                        "candidate_label_display": "",
                        "scope_broad_sub_micro": "",
                        "fit_1_5": "",
                        "confidence_1_5": "",
                        "evidence_recording_mbids": "",
                        "unsure": "",
                        "unsupported": "",
                        "access_failure": "",
                        "notes": "",
                    }
                )
    with (out / "neighbor-form.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "pair_item_id",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "candidate_A_display",
                "candidate_B_display",
                "popularity_baseline_display",
                "preferred_candidate_A_B_tie_neither",
                "cultural_relevance_1_5",
                "sonic_relevance_1_5",
                "confidence_1_5",
                "unsupported_query",
                "unsure",
                "access_failure",
                "notes",
            ],
        )
        w.writeheader()
        for row in pair_tasks:
            for slot in (1, 2):
                w.writerow(
                    {
                        "pair_item_id": row["pair_item_id"],
                        "reviewer_slot": slot,
                        "reviewer_id": "",
                        "familiarity_0_4": "",
                        "conflict_description": "",
                        "candidate_A_display": "",
                        "candidate_B_display": "",
                        "popularity_baseline_display": "",
                        "preferred_candidate_A_B_tie_neither": "",
                        "cultural_relevance_1_5": "",
                        "sonic_relevance_1_5": "",
                        "confidence_1_5": "",
                        "unsupported_query": "",
                        "unsure": "",
                        "access_failure": "",
                        "notes": "",
                    }
                )
    (out / "neighbor-items.json").write_text(
        json.dumps(pair_tasks, indent=2) + "\n", encoding="utf-8"
    )


def _write_recording_forms(
    out: Path, artists: list[dict[str, Any]], provider_map: dict[str, dict[str, Any]]
) -> None:
    """Write recording forms."""
    all_recordings = []
    for artist in artists:
        for rec in sorted(artist.get("recordings", []), key=lambda r: r["recording_mbid"]):
            dest = provider_map.get(rec["recording_mbid"], {}).get("destinations", [])
            all_recordings.append(
                {
                    "item_id": f"R{len(all_recordings) + 1:03d}",
                    "recording_mbid": rec["recording_mbid"],
                    "title": rec["title"],
                    "recording_url": rec["url"],
                    "artist_mbid": artist["artist_mbid"],
                    "artist_name": artist["name"],
                    "credited_artist_mbids": rec["credited_artist_mbids"],
                    "credit_verified": rec.get("verification"),
                    "provider_destinations": dest,
                    "access_status": "destination_found_availability_not_checked"
                    if dest
                    else "no_destination_found",
                    "listening_permission": "not established by this destination record",
                    "region": "unknown",
                    "checked_at": None,
                }
            )
    (out / "exact-recording-listening-cohort.json").write_text(
        json.dumps(
            {
                "source_recordings": len(all_recordings),
                "provider_destinations_found": sum(
                    bool(r["provider_destinations"]) for r in all_recordings
                ),
                "items": all_recordings,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "exact-recording-reviewer-assignments.json").write_text(
        json.dumps(
            [
                {
                    "item_id": r["item_id"],
                    "reviewer_slot": s,
                    "reviewer_id": "",
                    "status": "unassigned",
                }
                for r in all_recordings
                for s in (1, 2)
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out / "exact-recording-review-form.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "item_id",
                "recording_mbid",
                "artist_name",
                "title",
                "recording_url",
                "known_provider_destinations",
                "known_access_status",
                "reviewer_slot",
                "reviewer_id",
                "familiarity_0_4",
                "conflict_description",
                "exact_credit_match",
                "permitted_provider_url",
                "region_date_availability",
                "access_failure",
                "recording_fit_1_5",
                "defining_role_central_recent_emerging_other",
                "diversity_value_1_5",
                "unsure",
                "notes",
            ],
        )
        w.writeheader()
        for rec in all_recordings:
            for slot in (1, 2):
                w.writerow(
                    {
                        "item_id": rec["item_id"],
                        "recording_mbid": rec["recording_mbid"],
                        "artist_name": rec["artist_name"],
                        "title": rec["title"],
                        "recording_url": rec["recording_url"],
                        "known_provider_destinations": " ".join(
                            d["url"] for d in rec["provider_destinations"]
                        ),
                        "known_access_status": rec["access_status"],
                        "reviewer_slot": slot,
                        "reviewer_id": "",
                        "familiarity_0_4": "",
                        "conflict_description": "",
                        "exact_credit_match": "",
                        "permitted_provider_url": "",
                        "region_date_availability": "",
                        "access_failure": "",
                        "recording_fit_1_5": "",
                        "defining_role_central_recent_emerging_other": "",
                        "diversity_value_1_5": "",
                        "unsure": "",
                        "notes": "",
                    }
                )


def _write_packet_instructions(out: Path, coordinator: Path) -> None:
    """Write packet instructions."""
    request = (
        "We need independent musical judgments for an open music discovery "
        "project. Could you review a frozen 60-artist cohort drawn from our "
        "declared 150-artist engineering denominator? Each artist item needs "
        "two independent listeners. The packet shows exact artist identities "
        "and, where available, exact credited recordings; please listen only "
        "through a provider you are permitted to use and record access "
        "failures explicitly. We ask you to rate broad/subgenre/micro "
        "description fit, separately judge cultural and sonic neighbor "
        "relevance, and assess recording fit/diversity. A separate "
        "exact-recording cohort contains all 36 credited examples; 9 have a "
        "literal external provider destination, with current availability and "
        "permission still unchecked. You may answer unsure or unsupported. "
        "Please declare familiarity and conflicts. Method names, source votes, "
        "and confidence values are hidden during review. Return completed "
        "forms with your reviewer ID; we will preserve both independent "
        "answers and disagreements. Region/language/era are unknown in this "
        "engineering cohort, so this review cannot support a global coverage "
        "claim. No listening access or judgments have been assumed in advance."
    )
    (out / "listener-request.txt").write_text(request + "\n", encoding="utf-8")
    (out / "README.md").write_text(
        (
            "# Frozen musical review packet\n\nUse this packet to collect "
            "independent judgments against the selected 150-artist open-build "
            "denominator. `declaration.json` freezes scope, seed, sample rules and "
            "interpretation limits; `cohort.json` preserves sampled exact "
            "identities and available credited recording refs. Source genre IDs, "
            "source tags, and evidence-volume strata are in the sibling "
            "coordinator-only "
            "`musical-review-packet-coordinator/selected150-source-key.json`; hide "
            "that key until judgments are collected. Candidate labels and neighbor "
            "pairs remain blank until the selected candidate outputs are frozen. "
            "The CSV files contain two blank reviewer rows per item and are not "
            "results.\n\nBefore distribution, a coordinator must freeze candidate "
            "outputs, populate displayed labels and A/B pairs, and store "
            "method-to-letter assignments in the sibling coordinator directory. Do "
            "not infer listening permission from MusicBrainz links: the separate "
            "exact-recording roster carries literal provider destinations for 9 of "
            "36 examples, with availability and permission still unchecked. Check "
            "the provider for the reviewer and region, then record exact-match and "
            "access status.\n\nEach item needs two independent reviewers. Retain "
            "both rows, uncertainty, unsupported judgments and access failures. "
            "Record adjudication separately. Region, language and era are unknown "
            "in the source roster; this packet cannot establish global "
            "coverage.\n\nRebuild with `python "
            "scripts/build_musical_review_packet.py --source PATH "
            "--provider-destinations PATH --output "
            "docs/foundation/musical-review-packet`. Input SHA-256 values are "
            "frozen in `declaration.json`; changing the source, selection rule or "
            "thresholds requires a new revision.\n"
        ),
        encoding="utf-8",
    )
    manifest = {
        p.relative_to(out).as_posix(): sha(p)
        for p in sorted(out.rglob("*"))
        if p.is_file()
        and p.name != "manifest.json"
        and p.relative_to(out).parts[0] not in {"fma-full", "fma-full-coordinator"}
        and not any(part.endswith("coordinator") for part in p.relative_to(out).parts[:-1])
    }
    (out / "manifest.json").write_text(
        json.dumps({"sha256": manifest}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    coordinator_manifest = {
        p.relative_to(coordinator).as_posix(): sha(p)
        for p in sorted(coordinator.rglob("*"))
        if p.is_file() and p.name != "manifest.json"
    }
    (coordinator / "manifest.json").write_text(
        json.dumps({"sha256": coordinator_manifest}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Build a review packet from the declared source projection."""
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source",
        type=Path,
        default=Path("/dev/shm/opennoise-taxonomy-review-v3/artists/data.json"),  # noqa: S108
    )
    p.add_argument("--output", type=Path, default=Path("docs/foundation/musical-review-packet"))
    p.add_argument("--provider-destinations", type=Path)
    a = p.parse_args()
    sys.stdout.write(
        json.dumps(build(a.source, a.output, a.provider_destinations), sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
