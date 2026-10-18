"""Aggregate retained FMA44 track predictions by native artist, preserving split roles."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json, sha256_file
from opennoise.ml.fma_acoustic_baseline import _json_rows
from opennoise.ml.fma_memberships import replay_membership_pack

PARTITIONS = ("calibration", "confirmation", "test_diagnostic")
MAX_INPUT_BYTES = 24_000_000
MAX_OUTPUT_BYTES = 24_000_000
MAX_TRACKS = 110_000


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path.absolute(), *path.absolute().parents)):
        raise ValueError("Symlinked artist export input or output")


def aggregate_partition(  # noqa: C901 - identity joins and count denominators stay together.
    predictions: list[dict[str, Any]], identities: dict[int, dict[str, Any]], partition: str
) -> dict[str, Any]:
    """Count saved track predictions only; source target labels never supply evidence."""
    if partition not in PARTITIONS:
        raise ValueError("Unknown saved membership partition")
    artists: dict[int, Any] = {}
    seen: set[int] = set()
    unresolved: list[int] = []
    for prediction in predictions:
        track = prediction["track_id"]
        identity = identities.get(track)
        if identity is None or track in seen:
            raise ValueError("Missing or duplicate native track identity")
        seen.add(track)
        if (
            identity["fold"] != (2 if partition == "test_diagnostic" else 1)
            or identity["component_id"] != prediction["component_id"]
        ):
            raise ValueError("Prediction split/component differs from native identity ledger")
        if not identity["artist_known"]:
            unresolved.append(track)
            continue
        artist = identity["artist_id"]
        if type(artist) is not int or artist <= 0:
            raise ValueError("Known artist requires a positive native artist ID")
        row = artists.setdefault(
            artist,
            {
                "component_id": identity["component_id"],
                "track_ids": [],
                "abstentions": Counter(),
                "genres": {},
            },
        )
        if row["component_id"] != identity["component_id"]:
            raise ValueError("One native artist occurs in multiple identity components")
        row["track_ids"].append(track)
        if prediction["abstention"] is not None:
            row["abstentions"][prediction["abstention"]] += 1
        for member in prediction["memberships"]:
            row["genres"].setdefault(member["genre_id"], []).append(track)
    output = []
    genre_artists: dict[int, list[dict[str, int]]] = {}
    for artist, row in sorted(artists.items()):
        genre_evidence = []
        for genre, tracks in sorted(row["genres"].items()):
            genre_evidence.append(
                {
                    "genre_id": genre,
                    "contributing_track_ids": sorted(tracks),
                    "nominated_track_fraction": len(tracks) / len(row["track_ids"]),
                }
            )
            genre_artists.setdefault(genre, []).append(
                {"artist_id": artist, "contributing_track_count": len(tracks)}
            )
        output.append(
            {
                "artist_id": artist,
                "component_id": row["component_id"],
                "track_ids": sorted(row["track_ids"]),
                "abstention_counts": dict(sorted(row["abstentions"].items())),
                "genre_evidence": genre_evidence,
            }
        )
    return {
        "track_count": len(seen),
        "unresolved_artist_track_ids": sorted(unresolved),
        "artist_count": len(output),
        "artists": output,
        "genres": [
            {"genre_id": genre, "artists": rows} for genre, rows in sorted(genre_artists.items())
        ],
    }


def _verify_inputs(
    saved_pack: Path, saved_pin: str, memberships: Path, membership_pin: str
) -> None:
    """Bind bounded input inventories to caller-held receipts before replay."""
    for root, pin in ((saved_pack, saved_pin), (memberships, membership_pin)):
        files = list(root.rglob("*"))
        if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in files):
            raise ValueError("Artist export inputs contain links or special files")
        if sum(p.stat().st_size for p in files if p.is_file()) > MAX_INPUT_BYTES:
            raise ValueError("Artist export input byte cap exceeded")
        if sha256_file(root / "pack-receipt.json")[0] != pin:
            raise ValueError("Artist export input differs from external receipt pin")


def export_artist_evidence(
    saved_pack: Path, saved_pin: str, memberships: Path, membership_pin: str, output: Path
) -> dict[str, Any]:
    """Verify existing saved predictions, then publish one bounded artist/genre export."""
    for path in (saved_pack, memberships, output):
        _safe(path)
    if output.exists() or any(
        output.resolve().is_relative_to(p.resolve()) for p in (saved_pack, memberships)
    ):
        raise ValueError("Artist export must be fresh and outside input custody")
    _verify_inputs(saved_pack, saved_pin, memberships, membership_pin)
    replay_membership_pack(saved_pack, memberships)
    identities = {}
    for row in _json_rows(saved_pack / "native-folds.jsonl.zst"):
        track = row["track_id"]
        if track in identities or len(identities) >= MAX_TRACKS:
            raise ValueError("Duplicate native identity or track cap exceeded")
        identities[track] = row
    partitions = {
        name: aggregate_partition(
            list(_json_rows(memberships / f"{name}-memberships.jsonl.zst")), identities, name
        )
        for name in PARTITIONS
    }
    seen_artists: set[int] = set()
    seen_components: set[int] = set()
    for partition in partitions.values():
        artists = {r["artist_id"] for r in partition["artists"]}
        components = {r["component_id"] for r in partition["artists"]}
        if artists & seen_artists or components & seen_components:
            raise ValueError("Native artist/component leaks across saved partitions")
        seen_artists.update(artists)
        seen_components.update(components)
    receipt = json.loads((saved_pack / "pack-receipt.json").read_bytes())
    report = {
        "revision": "fma44-saved-artist-evidence-v1",
        "saved_pack_receipt_sha256": saved_pin,
        "membership_receipt_sha256": membership_pin,
        "producer_sha256": sha256_file(Path(__file__))[0],
        "license": receipt["license"],
        "attribution": receipt["attribution"],
        "artist_namespace": "FMA/native-artist-id",
        "track_namespace": "FMA/native-track-id",
        "scope": {
            "feature_family": "historical FMA44 mean channels",
            "role": "saved model track-membership observations grouped by native artist",
            "artist_genre_facts": False,
            "public_product_promotion_authorized": False,
            "musical_probability": False,
            "musical_relevance_established": False,
            "native_source_replay": False,
            "model_refit": False,
            "calibration_changed": False,
            "heldout_targets_used_for_aggregation": False,
            "fma518_evaluation": False,
            "test_previously_observed": True,
            "denominator": "all nominated queries per artist/partition, including abstentions",
        },
        "partitions": partitions,
    }
    raw = canonical_json(report) + b"\n"
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError("Artist export exceeds output byte cap")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    return {
        "sha256": sha256_file(output)[0],
        "bytes": len(raw),
        "partitions": {
            k: {f: v[f] for f in ("track_count", "artist_count")} for k, v in partitions.items()
        },
    }
