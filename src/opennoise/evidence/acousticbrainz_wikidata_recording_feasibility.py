"""Replay the bounded AcousticBrainz/Wikidata recording-diagnostic feasibility count."""

from __future__ import annotations

import bz2
import hashlib
import json
import sqlite3
import unicodedata
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_SHA256 = "d5b9eaef344864cd3c4d0bf1551e29b2fbcb23f9e28d1b7180cbdfa4dee704e3"
_CREDIT_SHA256 = "100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63"
_PUBLIC_SHA256 = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_MAX_SOURCE_ROWS = 200_000
_HEADER = ("recordingmbid", "releasegroupmbid", *(f"genre{i}" for i in range(1, 20)))


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: object) -> Sha256:
    return hashlib.sha256(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _normalise(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class AcousticBrainzWikidataFeasibilityReport(FrozenModel):
    """Aggregate-only proof of a frozen, positive-only recording diagnostic ceiling."""

    revision: str = "acousticbrainz-wikidata-recording-feasibility-v1"
    source_sha256: Sha256
    credit_database_sha256: Sha256
    public_database_sha256: Sha256
    frozen_recording_count: int = Field(ge=0)
    frozen_artist_mbid_count: int = Field(ge=0)
    frozen_artist_mbid_public_match_count: int = Field(ge=0)
    frozen_rows_with_direct_wikidata_p136: int = Field(ge=0)
    source_labels_interpreted_after_freeze: bool = True
    source_label_occurrence_count: int = Field(ge=0)
    source_distinct_label_count: int = Field(ge=0)
    unique_exact_target_label_count: int = Field(ge=0)
    rows_with_unique_exact_target_label: int = Field(ge=0)
    direct_wikidata_p136_exact_label_hits: int = Field(ge=0)
    independent_artist_genre_gold_ready: bool = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def verify_no_go_receipt(self) -> AcousticBrainzWikidataFeasibilityReport:
        """Require the retained source snapshots and preserve the no-go boundary."""
        if self.source_sha256 != _SOURCE_SHA256:
            raise ValueError("source archive hash is not pinned")
        if self.credit_database_sha256 != _CREDIT_SHA256:
            raise ValueError("credit database hash is not pinned")
        if self.public_database_sha256 != _PUBLIC_SHA256:
            raise ValueError("public database hash is not pinned")
        if self.frozen_rows_with_direct_wikidata_p136 > self.frozen_recording_count:
            raise ValueError("P136 rows exceed frozen recording cohort")
        if self.direct_wikidata_p136_exact_label_hits > self.rows_with_unique_exact_target_label:
            raise ValueError("exact-label hits exceed exact-label rows")
        if self.output_sha256 != _hash_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("feasibility receipt hash does not replay")
        return self


def audit_acousticbrainz_wikidata_recording_feasibility(
    source: Path, credit_database: Path, public_database: Path
) -> AcousticBrainzWikidataFeasibilityReport:
    """Freeze exact IDs and P136 predictions before reading any source genre column."""
    hashes = tuple(_sha256_file(path) for path in (source, credit_database, public_database))
    if hashes != (_SOURCE_SHA256, _CREDIT_SHA256, _PUBLIC_SHA256):
        raise ValueError("one or more feasibility inputs do not match their pinned hashes")
    source_pairs = _read_source_pairs(source)
    frozen = _freeze_exact_credit_cohort(credit_database, source_pairs)
    predictions, target_names = _freeze_wikidata_predictions(public_database, frozen)
    label_counts = _measure_labels_after_freeze(source, frozen, predictions, target_names)
    fields = {
        "revision": "acousticbrainz-wikidata-recording-feasibility-v1",
        "source_sha256": hashes[0],
        "credit_database_sha256": hashes[1],
        "public_database_sha256": hashes[2],
        "frozen_recording_count": len(frozen),
        "frozen_artist_mbid_count": len({artist for _, _, artist in frozen}),
        "frozen_artist_mbid_public_match_count": len(predictions),
        "frozen_rows_with_direct_wikidata_p136": sum(
            bool(predictions.get(artist)) for _, _, artist in frozen
        ),
        "source_labels_interpreted_after_freeze": True,
        **label_counts,
        "independent_artist_genre_gold_ready": False,
    }
    return AcousticBrainzWikidataFeasibilityReport.model_validate(
        {**fields, "output_sha256": _hash_json(fields)}
    )


def _read_source_pairs(source: Path) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    with bz2.open(source, "rt", encoding="utf-8") as stream:
        if tuple(stream.readline().rstrip("\n").split("\t")) != _HEADER:
            raise ValueError("source header is not the pinned Genre Dataset schema")
        for row_number, line in enumerate(stream, start=1):
            if row_number > _MAX_SOURCE_ROWS:
                raise ValueError("source exceeds bounded row count")
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(_HEADER):
                raise ValueError("source row does not match pinned schema")
            pairs.add((str(UUID(fields[0])), str(UUID(fields[1]))))
    return frozenset(pairs)


def _freeze_exact_credit_cohort(
    credit_database: Path, source_pairs: frozenset[tuple[str, str]]
) -> tuple[tuple[str, str, str], ...]:
    query = """
    WITH recording_ids AS (
      SELECT i.entity_id id, i.normalized_value recording_mbid FROM entity_identifiers i
      JOIN identifier_types t ON t.id=i.identifier_type_id JOIN recordings r ON r.id=i.entity_id
      WHERE t.type_key='musicbrainz_recording_id'
    ), groups AS (
      SELECT tr.recording_id id, i.normalized_value group_mbid FROM tracks tr
      JOIN media m ON m.id=tr.medium_id JOIN releases r ON r.id=m.release_id
      JOIN release_groups g ON g.id=r.release_group_id
      JOIN entity_identifiers i ON i.entity_id=g.id
      JOIN identifier_types t ON t.id=i.identifier_type_id
      WHERE t.type_key='musicbrainz_release_group_id'
    ), credits AS (
      SELECT e.entity_id id, COUNT(DISTINCT e.artist_credit_id) credits,
        COUNT(DISTINCT m.artist_id) artists, COUNT(DISTINCT m.position) positions,
        MIN(m.artist_id) artist_id
      FROM entity_artist_credits e
      JOIN artist_credit_members m ON m.artist_credit_id=e.artist_credit_id
      WHERE e.credit_kind='primary' GROUP BY e.entity_id
    ), artist_ids AS (
      SELECT i.entity_id artist_id, i.normalized_value artist_mbid FROM entity_identifiers i
      JOIN identifier_types t ON t.id=i.identifier_type_id WHERE t.type_key='musicbrainz_artist_id'
    )
    SELECT r.recording_mbid, g.group_mbid, a.artist_mbid FROM recording_ids r
    JOIN groups g ON g.id=r.id
    JOIN credits c ON c.id=r.id JOIN artist_ids a ON a.artist_id=c.artist_id
    WHERE c.credits=1 AND c.artists=1 AND c.positions=1
    """
    with sqlite3.connect(f"file:{credit_database}?mode=ro", uri=True) as database:
        rows = database.execute(query).fetchall()
    frozen: list[tuple[str, str, str]] = []
    for recording, group, artist in rows:
        if (
            not isinstance(recording, str)
            or not isinstance(group, str)
            or not isinstance(artist, str)
        ):
            raise TypeError("credit cohort contains a non-text identifier")
        if (recording, group) in source_pairs:
            frozen.append((recording, group, artist))
    return tuple(sorted(frozen))


def _freeze_wikidata_predictions(
    public_database: Path, frozen: tuple[tuple[str, str, str], ...]
) -> tuple[dict[str, frozenset[str]], dict[str, int]]:
    artist_mbids = {artist for _, _, artist in frozen}
    with sqlite3.connect(f"file:{public_database}?mode=ro", uri=True) as database:
        artists = dict(
            database.execute(
                """SELECT i.normalized_value, i.entity_id FROM entity_identifiers i
                   JOIN identifier_types t ON t.id=i.identifier_type_id
                   WHERE t.type_key='musicbrainz_artist_id'"""
            )
        )
        target_rows = database.execute("SELECT id, name FROM genres").fetchall()
        values = database.execute(
            """SELECT i.normalized_value, g.name FROM artist_genre_evidence e
               JOIN entity_identifiers i ON i.entity_id=e.artist_id
               JOIN identifier_types t ON t.id=i.identifier_type_id
               JOIN genres g ON g.id=e.genre_id
               WHERE t.type_key='musicbrainz_artist_id' AND e.method_key='wikidata_p136'
                 AND e.evidence_kind='direct_source_claim'"""
        ).fetchall()
    predictions: dict[str, set[str]] = {mbid: set() for mbid in artist_mbids if mbid in artists}
    for mbid, name in values:
        if mbid in predictions:
            predictions[mbid].add(_normalise(name))
    target_names: dict[str, int] = {}
    duplicates: set[str] = set()
    for target_id, name in target_rows:
        key = _normalise(name)
        if key in target_names:
            duplicates.add(key)
        else:
            target_names[key] = target_id
    return {mbid: frozenset(names) for mbid, names in predictions.items()}, {
        key: target for key, target in target_names.items() if key not in duplicates
    }


def _measure_labels_after_freeze(
    source: Path,
    frozen: tuple[tuple[str, str, str], ...],
    predictions: dict[str, frozenset[str]],
    unique_target_names: dict[str, int],
) -> dict[str, int]:
    by_pair = {(recording, group): artist for recording, group, artist in frozen}
    occurrences = 0
    labels: set[str] = set()
    matching_rows = hits = 0
    with bz2.open(source, "rt", encoding="utf-8") as stream:
        stream.readline()
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            artist = by_pair.get((fields[0], fields[1]))
            if artist is None:
                continue
            row_labels = tuple(_normalise(label) for label in fields[2:] if label)
            occurrences += len(row_labels)
            labels.update(row_labels)
            exact = set(row_labels) & unique_target_names.keys()
            if exact:
                matching_rows += 1
                hits += bool(exact & predictions.get(artist, frozenset()))
    return {
        "source_label_occurrence_count": occurrences,
        "source_distinct_label_count": len(labels),
        "unique_exact_target_label_count": len(labels & unique_target_names.keys()),
        "rows_with_unique_exact_target_label": matching_rows,
        "direct_wikidata_p136_exact_label_hits": hits,
    }
