"""Build and verify a source-isolated, positive-only recording diagnostic.

Prediction construction reads only AcousticBrainz recording identifiers, the
credit materialization, and direct Wikidata P136 rows.  It writes the frozen
prediction artifact and receipt before this module opens a source label field.
"""

from __future__ import annotations

import bz2
import hashlib
import json
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

_SOURCE_SHA256 = "d5b9eaef344864cd3c4d0bf1551e29b2fbcb23f9e28d1b7180cbdfa4dee704e3"
_CREDIT_SHA256 = "100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63"
_PUBLIC_SHA256 = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_MAX_SOURCE_ROWS = 200_000
_HEADER = ("recordingmbid", "releasegroupmbid", *(f"genre{i}" for i in range(1, 20)))
_FORBIDDEN_INPUTS = (
    "musicbrainz_artist_tags",
    "musicbrainz_recording_genres",
    "musicbrainz_release_group_genres",
    "historical_every_noise",
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _sha256_file(path: Path) -> Sha256:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: object) -> Sha256:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            default=_json_default,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot serialize {type(value).__name__} into a diagnostic hash")


def _normalise(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class DiagnosticSource(FrozenModel):
    """One permitted construction input with an exact content hash."""

    role: Literal[
        "acousticbrainz_identifier_columns",
        "musicbrainz_credit_membership",
        "wikidata_direct_p136_and_target_names",
    ]
    sha256: Sha256


class ForbiddenInputExclusion(FrozenModel):
    """One input class intentionally absent from prediction construction."""

    input_kind: Literal[
        "musicbrainz_artist_tags",
        "musicbrainz_recording_genres",
        "musicbrainz_release_group_genres",
        "historical_every_noise",
    ]
    used: Literal[False] = False


class FrozenRecordingPrediction(FrozenModel):
    """A direct-P136 prediction frozen for one exact recording identity."""

    recording_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    predicted_target_names: tuple[str, ...]


class AcousticBrainzWikidataPredictionArtifact(FrozenModel):
    """The complete pre-label prediction set and the target names used later."""

    revision: Literal["acousticbrainz-wikidata-recording-predictions-v1"] = (
        "acousticbrainz-wikidata-recording-predictions-v1"
    )
    predictions: tuple[FrozenRecordingPrediction, ...]
    unique_target_names: tuple[str, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def verify_hash_and_order(self) -> AcousticBrainzWikidataPredictionArtifact:
        """Require a canonical, self-verifying prediction artifact."""
        if self.predictions != tuple(sorted(self.predictions, key=lambda row: row.recording_mbid)):
            raise ValueError("prediction rows are not sorted by recording MBID")
        if len({row.recording_mbid for row in self.predictions}) != len(self.predictions):
            raise ValueError("prediction recording MBIDs are not unique")
        if self.unique_target_names != tuple(sorted(set(self.unique_target_names))):
            raise ValueError("unique target names are not sorted and unique")
        if self.output_sha256 != _hash_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("prediction artifact hash does not replay")
        return self


class AcousticBrainzWikidataPredictionReceipt(FrozenModel):
    """Construction receipt that binds the allowed inputs and explicit exclusions."""

    revision: Literal["acousticbrainz-wikidata-recording-prediction-receipt-v1"] = (
        "acousticbrainz-wikidata-recording-prediction-receipt-v1"
    )
    construction_program_sha256: Sha256
    source_inputs: tuple[DiagnosticSource, ...]
    forbidden_input_exclusions: tuple[ForbiddenInputExclusion, ...]
    prediction_count: int = Field(ge=0)
    prediction_logical_sha256: Sha256
    prediction_file_sha256: Sha256
    labels_read_during_construction: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def verify_receipt(self) -> AcousticBrainzWikidataPredictionReceipt:
        """Require the complete permitted-input and forbidden-input declaration."""
        expected_roles = (
            "acousticbrainz_identifier_columns",
            "musicbrainz_credit_membership",
            "wikidata_direct_p136_and_target_names",
        )
        if tuple(source.role for source in self.source_inputs) != expected_roles:
            raise ValueError("prediction receipt has an unexpected construction input")
        if tuple(item.input_kind for item in self.forbidden_input_exclusions) != _FORBIDDEN_INPUTS:
            raise ValueError("prediction receipt does not exclude every forbidden input")
        if any(item.used for item in self.forbidden_input_exclusions):
            raise ValueError("prediction receipt declares a forbidden input as used")
        if self.output_sha256 != _hash_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("prediction receipt hash does not replay")
        return self


class AcousticBrainzWikidataPositiveOnlyDiagnostic(FrozenModel):
    """Aggregate positive-label overlap after a verified prediction freeze."""

    revision: Literal["acousticbrainz-wikidata-positive-only-recording-diagnostic-v1"] = (
        "acousticbrainz-wikidata-positive-only-recording-diagnostic-v1"
    )
    prediction_file_sha256: Sha256
    prediction_receipt_file_sha256: Sha256
    prediction_count: int = Field(ge=0)
    source_label_occurrence_count: int = Field(ge=0)
    source_distinct_label_count: int = Field(ge=0)
    positive_rows_with_unique_target_label: int = Field(ge=0)
    positive_label_occurrences_with_unique_target_label: int = Field(ge=0)
    predicted_exact_label_overlap_count: int = Field(ge=0)
    negative_labels_used: Literal[False] = False
    artist_genre_gold_created: Literal[False] = False
    public_or_model_use_allowed: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def verify_positive_only_bounds(self) -> AcousticBrainzWikidataPositiveOnlyDiagnostic:
        """Keep aggregate counts within the frozen positive-only cohort."""
        if self.positive_rows_with_unique_target_label > self.prediction_count:
            raise ValueError("positive rows exceed frozen prediction count")
        if (
            self.predicted_exact_label_overlap_count
            > self.positive_label_occurrences_with_unique_target_label
        ):
            raise ValueError("predicted overlap exceeds positive label occurrences")
        if self.output_sha256 != _hash_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("positive-only diagnostic hash does not replay")
        return self


def write_frozen_wikidata_predictions(
    source: Path,
    credit_database: Path,
    public_database: Path,
    prediction_path: Path,
    receipt_path: Path,
) -> tuple[AcousticBrainzWikidataPredictionArtifact, AcousticBrainzWikidataPredictionReceipt]:
    """Write the prediction artifact and receipt before any label column is opened."""
    require_local_diagnostic_output(prediction_path)
    require_local_diagnostic_output(receipt_path)
    if prediction_path.exists() or receipt_path.exists():
        raise FileExistsError("refusing to overwrite a frozen prediction artifact or receipt")
    hashes = _require_pinned_inputs(source, credit_database, public_database)
    artifact = _build_prediction_artifact(source, credit_database, public_database)
    prediction_bytes = _json_bytes(artifact)
    receipt_fields = {
        "revision": "acousticbrainz-wikidata-recording-prediction-receipt-v1",
        "construction_program_sha256": _sha256_file(Path(__file__)),
        "source_inputs": (
            {"role": "acousticbrainz_identifier_columns", "sha256": hashes[0]},
            {"role": "musicbrainz_credit_membership", "sha256": hashes[1]},
            {"role": "wikidata_direct_p136_and_target_names", "sha256": hashes[2]},
        ),
        "forbidden_input_exclusions": tuple(
            {"input_kind": input_kind, "used": False} for input_kind in _FORBIDDEN_INPUTS
        ),
        "prediction_count": len(artifact.predictions),
        "prediction_logical_sha256": artifact.output_sha256,
        "prediction_file_sha256": hashlib.sha256(prediction_bytes).hexdigest(),
        "labels_read_during_construction": False,
    }
    receipt = AcousticBrainzWikidataPredictionReceipt.model_validate(
        {**receipt_fields, "output_sha256": _hash_json(receipt_fields)}
    )
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with prediction_path.open("xb") as output:
            output.write(prediction_bytes)
        with receipt_path.open("xb") as output:
            output.write(_json_bytes(receipt))
    except OSError:
        prediction_path.unlink(missing_ok=True)
        raise
    return artifact, receipt


def require_local_diagnostic_output(path: Path) -> None:
    """Reject diagnostic output paths inside the deployable static tree."""
    if path.resolve().is_relative_to(_REPOSITORY_ROOT / "dist"):
        raise ValueError("recording diagnostic outputs must not be written under dist")


def verify_frozen_wikidata_predictions(
    source: Path,
    credit_database: Path,
    public_database: Path,
    prediction_path: Path,
    receipt_path: Path,
) -> tuple[AcousticBrainzWikidataPredictionArtifact, AcousticBrainzWikidataPredictionReceipt]:
    """Replay the permitted construction and reject stale, altered, or broad lineage."""
    hashes = _require_pinned_inputs(source, credit_database, public_database)
    artifact = AcousticBrainzWikidataPredictionArtifact.model_validate_json(
        prediction_path.read_bytes()
    )
    receipt_bytes = receipt_path.read_bytes()
    receipt = AcousticBrainzWikidataPredictionReceipt.model_validate_json(receipt_bytes)
    if receipt.construction_program_sha256 != _sha256_file(Path(__file__)):
        raise ValueError(
            "prediction receipt construction program hash does not match this verifier"
        )
    if tuple(item.sha256 for item in receipt.source_inputs) != hashes:
        raise ValueError("prediction receipt source hashes do not match supplied inputs")
    if receipt.prediction_file_sha256 != _sha256_file(prediction_path):
        raise ValueError("prediction receipt file hash does not match prediction file")
    if receipt.prediction_count != len(artifact.predictions):
        raise ValueError("prediction receipt count does not match prediction file")
    if receipt.prediction_logical_sha256 != artifact.output_sha256:
        raise ValueError("prediction receipt logical hash does not match prediction file")
    expected = _build_prediction_artifact(source, credit_database, public_database)
    if artifact != expected:
        raise ValueError("prediction file does not replay from permitted direct-P136 inputs")
    return artifact, receipt


def diagnose_positive_only_recordings(
    source: Path,
    credit_database: Path,
    public_database: Path,
    prediction_path: Path,
    receipt_path: Path,
) -> AcousticBrainzWikidataPositiveOnlyDiagnostic:
    """Read source labels only after an exact prediction artifact has verified."""
    artifact, receipt = verify_frozen_wikidata_predictions(
        source, credit_database, public_database, prediction_path, receipt_path
    )
    counts = _measure_positive_labels_after_verification(source, artifact)
    fields = {
        "revision": "acousticbrainz-wikidata-positive-only-recording-diagnostic-v1",
        "prediction_file_sha256": _sha256_file(prediction_path),
        "prediction_receipt_file_sha256": _sha256_file(receipt_path),
        "prediction_count": receipt.prediction_count,
        **counts,
        "negative_labels_used": False,
        "artist_genre_gold_created": False,
        "public_or_model_use_allowed": False,
    }
    return AcousticBrainzWikidataPositiveOnlyDiagnostic.model_validate(
        {**fields, "output_sha256": _hash_json(fields)}
    )


def _require_pinned_inputs(
    source: Path, credit_database: Path, public_database: Path
) -> tuple[Sha256, ...]:
    hashes = tuple(_sha256_file(path) for path in (source, credit_database, public_database))
    if hashes != (_SOURCE_SHA256, _CREDIT_SHA256, _PUBLIC_SHA256):
        raise ValueError("one or more diagnostic inputs do not match their pinned hashes")
    return hashes


def _build_prediction_artifact(
    source: Path, credit_database: Path, public_database: Path
) -> AcousticBrainzWikidataPredictionArtifact:
    source_pairs = _read_source_identifier_pairs(source)
    cohort = _freeze_exact_credit_cohort(credit_database, source_pairs)
    predicted_names, target_names = _freeze_direct_p136_predictions(public_database, cohort)
    rows = tuple(
        FrozenRecordingPrediction(
            recording_mbid=recording,
            release_group_mbid=release_group,
            artist_mbid=artist,
            predicted_target_names=tuple(sorted(predicted_names.get(artist, frozenset()))),
        )
        for recording, release_group, artist in cohort
    )
    fields = {
        "revision": "acousticbrainz-wikidata-recording-predictions-v1",
        "predictions": rows,
        "unique_target_names": tuple(sorted(target_names)),
    }
    return AcousticBrainzWikidataPredictionArtifact.model_validate(
        {**fields, "output_sha256": _hash_json(fields)}
    )


def _read_source_identifier_pairs(source: Path) -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    with bz2.open(source, "rt", encoding="utf-8") as stream:
        if tuple(stream.readline().rstrip("\n").split("\t")) != _HEADER:
            raise ValueError("source header is not the pinned Genre Dataset schema")
        for row_number, line in enumerate(stream, start=1):
            if row_number > _MAX_SOURCE_ROWS:
                raise ValueError("source exceeds bounded row count")
            if line.count("\t") != len(_HEADER) - 1:
                raise ValueError("source row does not match pinned schema")
            first, separator, rest = line.partition("\t")
            second, separator_after_second, _labels = rest.partition("\t")
            if not separator or not separator_after_second:
                raise ValueError("source row does not have two identifier columns")
            pairs.add((str(UUID(first)), str(UUID(second))))
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
      JOIN release_groups g ON g.id=r.release_group_id JOIN entity_identifiers i ON i.entity_id=g.id
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
    JOIN groups g ON g.id=r.id JOIN credits c ON c.id=r.id
    JOIN artist_ids a ON a.artist_id=c.artist_id
    WHERE c.credits=1 AND c.artists=1 AND c.positions=1
    """
    with closing(sqlite3.connect(f"file:{credit_database}?mode=ro", uri=True)) as database:
        values = database.execute(query).fetchall()
    rows: list[tuple[str, str, str]] = []
    for recording, release_group, artist in values:
        if not all(isinstance(value, str) for value in (recording, release_group, artist)):
            raise TypeError("credit cohort contains a non-text identifier")
        if (recording, release_group) in source_pairs:
            rows.append((recording, release_group, artist))
    return tuple(sorted(rows))


def _freeze_direct_p136_predictions(
    public_database: Path, cohort: tuple[tuple[str, str, str], ...]
) -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    artist_mbids = {artist for _, _, artist in cohort}
    with closing(sqlite3.connect(f"file:{public_database}?mode=ro", uri=True)) as database:
        artist_rows = database.execute(
            """SELECT i.normalized_value FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE t.type_key='musicbrainz_artist_id'"""
        ).fetchall()
        target_rows = database.execute("SELECT name FROM genres").fetchall()
        p136_rows = database.execute(
            """SELECT i.normalized_value, g.name FROM artist_genre_evidence e
               JOIN entity_identifiers i ON i.entity_id=e.artist_id
               JOIN identifier_types t ON t.id=i.identifier_type_id JOIN genres g ON g.id=e.genre_id
               WHERE t.type_key='musicbrainz_artist_id' AND e.method_key='wikidata_p136'
                 AND e.evidence_kind='direct_source_claim'"""
        ).fetchall()
    known_artists = {value for (value,) in artist_rows if isinstance(value, str)}
    predictions: dict[str, set[str]] = {artist: set() for artist in artist_mbids & known_artists}
    for artist, name in p136_rows:
        if artist in predictions and isinstance(name, str):
            predictions[artist].add(_normalise(name))
    counts: dict[str, int] = {}
    for (name,) in target_rows:
        if not isinstance(name, str):
            raise TypeError("target genre name is not text")
        normalised = _normalise(name)
        counts[normalised] = counts.get(normalised, 0) + 1
    return (
        {artist: frozenset(names) for artist, names in predictions.items()},
        frozenset(name for name, count in counts.items() if count == 1),
    )


def _measure_positive_labels_after_verification(
    source: Path, artifact: AcousticBrainzWikidataPredictionArtifact
) -> dict[str, int]:
    predictions = {
        (row.recording_mbid, row.release_group_mbid): row for row in artifact.predictions
    }
    target_names = frozenset(artifact.unique_target_names)
    occurrences = 0
    labels: set[str] = set()
    positive_rows = positive_occurrences = predicted_overlap = 0
    with bz2.open(source, "rt", encoding="utf-8") as stream:
        if tuple(stream.readline().rstrip("\n").split("\t")) != _HEADER:
            raise ValueError("source header is not the pinned Genre Dataset schema")
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(_HEADER):
                raise ValueError("source row does not match pinned schema")
            row = predictions.get((fields[0], fields[1]))
            if row is None:
                continue
            row_labels = tuple(_normalise(label) for label in fields[2:] if label)
            occurrences += len(row_labels)
            labels.update(row_labels)
            positive = tuple(label for label in row_labels if label in target_names)
            if positive:
                positive_rows += 1
                positive_occurrences += len(positive)
                predicted_overlap += sum(label in row.predicted_target_names for label in positive)
    return {
        "source_label_occurrence_count": occurrences,
        "source_distinct_label_count": len(labels),
        "positive_rows_with_unique_target_label": positive_rows,
        "positive_label_occurrences_with_unique_target_label": positive_occurrences,
        "predicted_exact_label_overlap_count": predicted_overlap,
    }


def _json_bytes(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode()
