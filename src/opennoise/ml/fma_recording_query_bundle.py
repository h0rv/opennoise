"""Portable, pinned historical saved-rank lookup; no source or target reads at query time."""

# ruff: noqa: PLR2004 -- fixed artifact schemas and numeric contract bounds.

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from opennoise.ml import fma_acoustic_baseline as baseline
from opennoise.ml import fma_artist_neighbors as neighbors
from opennoise.ml import fma_encoder_bundle as artifact
from opennoise.ml import fma_memberships as memberships
from opennoise.ml import fma_recording_artists as recording
from opennoise.ml.fma_encoder_export import fresh_destination

REVISION = "fma44-saved-recording-query-bundle-v1"
FILES = {"lookup.json"}
NATIVE_COLUMNS = ["track_id", "artist_id", "artist_known", "component_id", "fold"]
SAVED_COLUMNS = ["track_id", "reason", "ranked_genre_ids"]
PARTITIONS = ("calibration", "confirmation", "test_diagnostic")
ARTIST_FIELDS = {
    "artist_id",
    "component_id",
    "track_ids",
    "ranking_supported_track_count",
    "ranked_source_annotation_candidates",
}
CANDIDATE_FIELDS = {"genre_id", "mean_reciprocal_track_rank", "contributing_track_count"}
REASONS = {None, "missing_feature_row", "missing_descriptors", "outside_training_support"}


def runtime() -> dict[str, Any]:
    """Bind only the lookup, selection, artifact and identity/partition implementation."""
    return {
        "versions": artifact.versions(),
        "code": {
            Path(m.__file__).name: artifact.sha(Path(m.__file__))
            for m in (artifact, baseline, memberships, neighbors, recording)
        },
        "bundle_code_sha256": artifact.sha(Path(__file__)),
        "bounds": [recording.MAX_QUERIES, recording.MAX_TRACK_ID, recording.TOP_K],
    }


def positive(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON scalar boundary.
    """Require native integer IDs rather than numeric lookalikes."""
    return type(value) is int and 0 < value <= recording.MAX_TRACK_ID


def native_rows(body: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Validate every native identity, including those without saved predictions."""
    rows = body["native"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= artifact.MAX_ROSTER:
        raise ValueError("Native roster bound differs")
    identities = {}
    artist_components = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != len(NATIVE_COLUMNS)
            or not all(positive(row[i]) for i in (0, 1, 3))
            or type(row[2]) is not bool
            or type(row[4]) is not int
            or row[4] != baseline.artist_group_fold(row[3])
            or row[0] in identities
        ):
            raise ValueError("Native identity, fold or duplicate differs")
        prior = artist_components.setdefault(row[1], (row[3], row[2]))
        if prior != (row[3], row[2]):
            raise ValueError("Native artist/component/known state conflicts")
        identities[row[0]] = dict(zip(NATIVE_COLUMNS, row, strict=True))
    return identities


def saved_rows(body: dict[str, Any], identities: dict[int, Any]) -> dict[int, dict[str, Any]]:
    """Validate saved query membership and preserve original abstentions."""
    rows = body["saved"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= artifact.MAX_ROSTER:
        raise ValueError("Saved row bound differs")
    saved = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != len(SAVED_COLUMNS)
            or not positive(row[0])
            or row[0] not in identities
            or row[0] in saved
            or row[1] not in REASONS
            or not isinstance(row[2], list)
            or len(row[2]) > recording.TOP_K
            or not all(positive(g) for g in row[2])
            or len(set(row[2])) != len(row[2])
            or (row[1] is not None and row[2])
        ):
            raise ValueError("Saved rank/identity/abstention differs")
        saved[row[0]] = dict(zip(SAVED_COLUMNS, row, strict=True))
    expected = {i for i, r in identities.items() if r["artist_known"] and r["fold"] in (1, 2)}
    if set(saved) != expected:
        raise ValueError("Saved queries differ from the full known heldout native roster")
    return saved


def partition_name(identity: dict[str, Any]) -> str:
    """Replay the original component-based historical partition without targets."""
    return (
        "test_diagnostic"
        if identity["fold"] == 2
        else "calibration"
        if memberships.calibration_half(identity["component_id"])
        else "confirmation"
    )


def validate_profile(  # noqa: C901 - identity joins and support checks form one boundary.
    row: dict[str, Any],
    identities: dict[int, Any],
    saved: dict[int, Any],
    name: str,
    seen: set[int],
) -> None:
    """Check exact track/artist/component/partition joins and support denominators."""
    if (
        set(row) != ARTIST_FIELDS
        or not positive(row["artist_id"])
        or not positive(row["component_id"])
    ):
        raise ValueError("Artist profile schema/identity differs")
    tracks = row["track_ids"]
    if (
        not isinstance(tracks, list)
        or not tracks
        or not all(positive(t) for t in tracks)
        or tracks != sorted(set(tracks))
        or any(t in seen for t in tracks)
    ):
        raise ValueError("Artist track roster duplicates or bounds differ")
    for track in tracks:
        identity = identities.get(track)
        if (
            track not in saved
            or identity is None
            or not identity["artist_known"]
            or identity["artist_id"] != row["artist_id"]
            or identity["component_id"] != row["component_id"]
            or partition_name(identity) != name
        ):
            raise ValueError("Profile native identity/partition join differs")
        seen.add(track)
    supported = sum(bool(saved[t]["ranked_genre_ids"]) for t in tracks)
    if (
        type(row["ranking_supported_track_count"]) is not int
        or row["ranking_supported_track_count"] != supported
    ):
        raise ValueError("Profile supported track count differs")
    genres = row["ranked_source_annotation_candidates"]
    if (
        not isinstance(genres, list)
        or len(genres) > recording.TOP_K
        or bool(genres) != bool(supported)
    ):
        raise ValueError("Profile candidate bounds/support differs")
    seen_genres = set()
    for genre in genres:
        if not isinstance(genre, dict) or set(genre) != CANDIDATE_FIELDS:
            raise ValueError("Profile candidate schema differs")
        score, count = genre["mean_reciprocal_track_rank"], genre["contributing_track_count"]
        if (
            not positive(genre["genre_id"])
            or genre["genre_id"] in seen_genres
            or type(count) is not int
            or not 1 <= count <= supported
            or type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 < score <= count / len(tracks) + 1e-12
        ):
            raise ValueError("Profile rank weights or contribution counts differ")
        seen_genres.add(genre["genre_id"])
    if genres != sorted(genres, key=lambda g: (-g["mean_reciprocal_track_rank"], g["genre_id"])):
        raise ValueError("Profile candidate ordering differs")


def validate(body: dict[str, Any]) -> tuple[dict[int, Any], dict[int, Any]]:
    """Reject unexpected data fields and inconsistent identities even after resealing."""
    if (
        set(body) != {"native_columns", "native", "saved_columns", "saved", "partitions"}
        or body["native_columns"] != NATIVE_COLUMNS
        or body["saved_columns"] != SAVED_COLUMNS
        or not isinstance(body["partitions"], dict)
        or set(body["partitions"]) != set(PARTITIONS)
    ):
        raise ValueError("Lookup schema differs")
    identities = native_rows(body)
    saved = saved_rows(body, identities)
    seen: set[int] = set()
    artists = set()
    components = {}
    for name, partition in body["partitions"].items():
        if (
            set(partition) != {"artists", "unresolved_artist_track_ids"}
            or partition["unresolved_artist_track_ids"] != []
            or not isinstance(partition["artists"], list)
            or len(partition["artists"]) > neighbors.MAX_ARTISTS
        ):
            raise ValueError("Partition profile bounds/fields differ")
        for row in partition["artists"]:
            validate_profile(row, identities, saved, name, seen)
            if (
                row["artist_id"] in artists
                or components.setdefault(row["component_id"], name) != name
            ):
                raise ValueError("Artist/component partition leakage")
            artists.add(row["artist_id"])
    if seen != set(saved):
        raise ValueError("Profiles do not cover every saved query exactly once")
    return identities, saved


def validate_provenance(provenance: dict[str, Any]) -> None:
    """Keep source attestations as bounded hashes/text, never executable paths."""
    names = {
        "native-folds.jsonl.zst",
        "validation-acoustic-ranks.jsonl.zst",
        "test-acoustic-ranks.jsonl.zst",
    }
    if (
        set(provenance)
        != {
            "saved_pack_receipt_sha256",
            "membership_receipt_sha256",
            "saved_inputs",
            "license",
            "attribution",
        }
        or set(provenance["saved_inputs"]) != names
        or provenance["license"] != "CC-BY-4.0"
        or any(
            not isinstance(provenance[k], str) or not 0 < len(provenance[k]) <= 4096
            for k in ("license", "attribution")
        )
    ):
        raise ValueError("Source provenance schema differs")
    pins = [
        provenance["saved_pack_receipt_sha256"],
        provenance["membership_receipt_sha256"],
        *provenance["saved_inputs"].values(),
    ]
    if any(not isinstance(pin, str) or re.fullmatch("[0-9a-f]{64}", pin) is None for pin in pins):
        raise ValueError("Source provenance pins differ")


def prepare(
    report: dict[str, Any],
    identities: dict[int, Any],
    saved: dict[int, Any],
    provenance: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Project verified state after full-rank artist aggregation; omit all target fields."""
    body = {
        "native_columns": NATIVE_COLUMNS,
        "native": [[r[k] for k in NATIVE_COLUMNS] for _, r in sorted(identities.items())],
        "saved_columns": SAVED_COLUMNS,
        "saved": [
            [track, r["reason"], r["ranked_genre_ids"][: recording.TOP_K]]
            for track, r in sorted(saved.items())
        ],
        "partitions": {
            name: {
                "unresolved_artist_track_ids": p["unresolved_artist_track_ids"],
                "artists": [{k: a[k] for k in ARTIST_FIELDS} for a in p["artists"]],
            }
            for name, p in report["partitions"].items()
        },
    }
    validate(body)
    validate_provenance(provenance)
    raw = artifact.encoded(body)
    metadata = {
        "revision": REVISION,
        "runtime": runtime(),
        "policy": recording.POLICY,
        "provenance": provenance,
    }
    # Include the final manifest in the same fixed 10 MB budget before publishing.
    binding = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    if (
        len(raw) + len(artifact.encoded({**metadata, "files": {"lookup.json": binding}}))
        > artifact.BUNDLE_BYTES
    ):
        raise ValueError("Saved lookup bundle byte guard exceeded")
    return raw, metadata


def publish(output: Path, raw: bytes, metadata: dict[str, Any]) -> str:
    """Publish a fresh closed bundle with its externally pinnable final manifest."""
    output.mkdir(parents=True, exist_ok=False)
    (output / "lookup.json").write_bytes(raw)
    return artifact.write_manifest(output, metadata, artifact.BUNDLE_BYTES)


def load(
    root: Path, pin: str
) -> tuple[dict[str, Any], dict[int, Any], dict[int, Any], dict[str, Any]]:
    """Read only the supplied closed bundle; never load original paths or targets."""
    try:
        manifest = artifact.read_artifact(root, pin, FILES, artifact.BUNDLE_BYTES)
        if (
            set(manifest) != {"revision", "runtime", "policy", "provenance", "files"}
            or manifest["revision"] != REVISION
            or artifact.encoded(manifest["runtime"]) != artifact.encoded(runtime())
            or artifact.encoded(manifest["policy"]) != artifact.encoded(recording.POLICY)
        ):
            raise ValueError("Lookup revision/runtime/policy differs")
        validate_provenance(manifest["provenance"])
        raw = (root / "lookup.json").read_bytes()
        body = json.loads(raw)
        if artifact.encoded(body) != raw:
            raise ValueError("Lookup data must be finite canonical JSON")
        identities, saved = validate(body)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("Malformed saved lookup bundle") from exc
    return body, identities, saved, manifest["provenance"]


def lookup(root: Path, pin: str, track_ids: list[int], output: Path) -> dict[str, Any]:
    """Write bounded query-only results from a relocated saved lookup bundle."""
    recording.validate_requests(track_ids)
    fresh_destination(output, (root,))
    body, identities, saved, provenance = load(root, pin)
    result = {
        "revision": REVISION,
        "bundle_manifest_sha256": pin,
        "license": provenance["license"],
        "attribution": provenance["attribution"],
        "source_provenance": provenance,
        "artist_namespace": "FMA/native-artist-id",
        "track_namespace": "FMA/native-track-id",
        "recording_query_policy": recording.POLICY,
        "candidate_evidence": "native artist IDs resolve within the pinned bundle partition",
        "recording_artist_queries": recording.query_recordings(
            track_ids, saved, identities, body["partitions"]
        ),
    }
    raw = artifact.encoded(result)
    if len(raw) > artifact.QUERY_BYTES:
        raise ValueError("Query result byte guard exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    return {"sha256": artifact.sha(output), "bytes": len(raw), "query_count": len(track_ids)}
