"""Compact direct Wikidata taxonomy for the source-separated music explorer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.ingest.wikidata.open_genre_taxonomy import verify_pack
from opennoise.pipeline.portable_foundation import CULTURAL_PACKS, project_portable_foundation

if TYPE_CHECKING:
    from pathlib import Path

DETAIL_SHARDS = 10
MAX_SHARD_BYTES = 200_000


def export_source_genres(  # noqa: C901 - preserve the direct source boundaries in one export.
    pack: Path,
    output: Path,
    files: dict[str, Any],
    *,
    foundation_root: Path | None = None,
) -> dict[str, Any]:
    """Replay retained captures and export names and directed P279 claims only.

    Index rows are ``[qid, name, english_label_missing]``. Detail shard number
    is numeric QID modulo ten. Parent rows are ``[qid, name, in_selected_cohort]``;
    children are selected QIDs. Neither relation transfers artist membership.
    """
    source = verify_pack(pack)
    entities = sorted(
        source["entities"],
        key=lambda row: ((row["english_label"] or row["qid"]).casefold(), int(row["qid"][1:])),
    )
    names = {row["qid"]: row["english_label"] or row["qid"] for row in entities}
    details: dict[str, dict[str, Any]] = {qid: {"parents": [], "children": []} for qid in names}
    claims = [row for row in source["claims"] if row["property_id"] == "P279"]
    internal_count = 0
    for claim in claims:
        child, parent = claim["genre_qid"], claim["value_qid"]
        selected = parent in names
        details[child]["parents"].append(
            [parent, names.get(parent, claim["value_label"] or parent), selected]
        )
        if selected:
            details[parent]["children"].append(child)
            internal_count += 1
    for detail in details.values():
        detail["parents"].sort(key=lambda row: int(row[0][1:]))
        detail["children"].sort(key=lambda qid: int(qid[1:]))
        detail["artists"] = []
    artists: dict[str, dict[str, Any]] = {}
    cultural_receipts = {}
    if foundation_root is not None:
        foundation = project_portable_foundation(foundation_root)
        genre_names = {row["genre_id"]: row["name"] for row in foundation["genres"]}
        for artist in foundation["artists"]:
            direct = [qid for qid in artist["direct_genres"] if qid in names]
            if not direct:
                continue
            mbid = artist["artist_mbid"]
            qids = artist["wikidata_ids"]
            artists[mbid] = {
                "name": artist["name"],
                "wikidata_id": qids[0] if len(qids) == 1 else None,
                "wikidata_ids": qids,
                "direct_genres": direct,
                "other_genres": [
                    [qid, genre_names[qid]] for qid in artist["direct_genres"] if qid not in names
                ],
                "source_url": f"https://musicbrainz.org/artist/{mbid}",
                "claims": [
                    {
                        "genre_qid": claim["value_qid"],
                        "property_id": "P136",
                        "wikidata_artist_id": claim["wikidata_artist_id"],
                        "source_url": claim["source"],
                        "capture_pack": claim["capture_pack"],
                        "source_sha256": claim["source_sha256"],
                        "observed_at": claim["observed_at"],
                    }
                    for claim in artist["claims"]
                    if claim["property_id"] == "P136" and claim["value_qid"] in names
                ],
            }
            for qid in direct:
                details[qid]["artists"].append(mbid)
        cultural_receipts = {
            name: sha256_file(foundation_root / "data/examples" / name / "receipt.json")[0]
            for name in CULTURAL_PACKS
        }
    index = {
        "revision": "source-genres-v1",
        "identity_namespace": "Wikidata_QID",
        "license": source["license"],
        "source_receipt_sha256": sha256_file(pack / "receipt.json")[0],
        "projection_sha256": sha256_file(pack / "projection.json")[0],
        "source_captures": source["source_captures"],
        "selection_possibly_truncated": source["selection_possibly_truncated"],
        "artist_memberships": sum(len(row["direct_genres"]) for row in artists.values()),
        "artist_claim_scope": "Direct Wikidata P136 only; never inherited through taxonomy",
        "cultural_receipts_sha256": cultural_receipts,
        "cross_source_equivalence": False,
        "relation": "P279: direct source subclass assertion",
        "detail_shards": DETAIL_SHARDS,
        "counts": {
            "genres": len(entities),
            "missing_english_labels": sum(row["english_label"] is None for row in entities),
            "subclass_claims": len(claims),
            "internal_subclass_claims": internal_count,
            "external_subclass_claims": len(claims) - internal_count,
            "artists": len(artists),
            "genres_with_direct_artists": sum(bool(row["artists"]) for row in details.values()),
        },
        "genres": [
            [row["qid"], names[row["qid"]], row["english_label"] is None] for row in entities
        ],
    }
    payloads = {"source-genres/index.json": canonical_json(index) + b"\n"}
    payloads["source-genres/artists.json"] = canonical_json({"artists": artists}) + b"\n"
    for shard in range(DETAIL_SHARDS):
        payloads[f"source-genres/{shard}.json"] = (
            canonical_json(
                {
                    "shard": shard,
                    "genres": {
                        qid: detail
                        for qid, detail in details.items()
                        if int(qid[1:]) % DETAIL_SHARDS == shard
                    },
                }
            )
            + b"\n"
        )
    if any(len(payload) > MAX_SHARD_BYTES for payload in payloads.values()):
        raise ValueError("source genre shard exceeds 200 KB")
    for relative, payload in payloads.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
        files[relative] = {"sha256": sha256_hex(payload), "bytes": len(payload)}
    return {
        "index": "source-genres/index.json",
        "counts": index["counts"],
        "license": index["license"],
        "source_receipt_sha256": index["source_receipt_sha256"],
        "projection_sha256": index["projection_sha256"],
        "bytes": sum(map(len, payloads.values())),
    }
