"""Independently reconstruct native FMA URL bridge assertions and complete denominators."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from opennoise.common import sha256_file
from opennoise.ingest.fma.corpus import source_rows, verify_sources


def audit(source: Path, pack: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - explicit independent census and custody checks.
    """Use a separate census and matching implementation, retaining zero recording recovery."""
    source_receipt = verify_sources(source)
    denominators: dict[str, dict[str, Any]] = {}
    url_ids: dict[str, dict[str, set[int]]] = {}
    for kind, table, id_field, url_field in (
        ("artist", "artists", "artist_id", "artist_url"),
        ("recording", "tracks", "track_id", "track_url"),
    ):
        member = source_receipt["members"][f"fma_metadata/raw_{table}.csv"]
        rows, verified, handles = source_rows(source, member)
        index: dict[str, set[int]] = defaultdict(set)
        identities = set()
        count = 0
        try:
            for row in rows:
                identity = int(row[id_field])
                if identity <= 0 or identity in identities:
                    raise ValueError("raw native identity is invalid or duplicated")
                identities.add(identity)
                count += 1
                if row[url_field]:
                    index[row[url_field]].add(identity)
            if not verified.complete:
                raise ValueError("raw native source did not reach verified EOF")
            denominators[kind] = {
                "rows": count,
                "source_bytes": verified.length,
                "source_sha256": verified.sha256.hexdigest(),
                "crc32": f"{verified.crc:08x}",
            }
        finally:
            for handle in handles:
                handle.close()
        url_ids[kind] = index
    receipt = json.loads((pack / "receipt.json").read_bytes())
    matches: dict[str, dict[int, set[str]]] = {kind: defaultdict(set) for kind in url_ids}
    page_bindings = {}
    seen_urls = set()
    ambiguous_native_urls = []
    for capture in receipt["captures"]:
        path = pack / capture["path"]
        digest, size = sha256_file(path)
        if digest != capture["sha256"] or size != capture["bytes"]:
            raise ValueError("native response bytes changed")
        page_bindings[capture["path"]] = {"sha256": digest, "bytes": size}
        page = json.loads(path.read_bytes())
        for url in page["urls"]:
            if str(UUID(url["id"])) != url["id"] or url["id"] in seen_urls:
                raise ValueError("URL native UUID is invalid or repeated")
            seen_urls.add(url["id"])
            for relation_group in url.get("relation-list", []):
                for relation in relation_group["relations"]:
                    if relation.get("direction") != "backward":
                        continue
                    for kind, index in url_ids.items():
                        if kind not in relation:
                            continue
                        mbid = relation[kind]["id"]
                        if str(UUID(mbid)) != mbid:
                            raise ValueError("related native identity is not a UUID")
                        native_ids = index.get(url["resource"], set())
                        if len(native_ids) > 1:
                            ambiguous_native_urls.append(
                                {
                                    "kind": kind,
                                    "url": url["resource"],
                                    "native_ids": sorted(native_ids),
                                    "musicbrainz_mbid": mbid,
                                }
                            )
                        for native_id in native_ids:
                            matches[kind][native_id].add(mbid)
    saved = json.loads((pack / "bridge.json").read_bytes())
    for kind, table in matches.items():
        for arm, singleton in (("resolved", True), ("conflicts", False)):
            reconstructed = {
                identity: sorted(identities)
                for identity, identities in table.items()
                if (len(identities) == 1) == singleton
            }
            projection = {row["fma_id"]: row["musicbrainz_mbids"] for row in saved[kind][arm]}
            if reconstructed != projection:
                raise ValueError("saved bridge differs from independent native assertion census")
        if saved[kind]["eligible"] != denominators[kind]["rows"]:
            raise ValueError("bridge omitted native denominator")
        if saved[kind]["unresolved"] != denominators[kind]["rows"] - len(saved[kind]["resolved"]):
            raise ValueError("bridge unresolved denominator changed")
    return {
        "exact_native_url_entity_assertions_match": True,
        "bridge_receipt_sha256": sha256_file(pack / "receipt.json")[0],
        "bridge_projection_sha256": sha256_file(pack / "bridge.json")[0],
        "source_receipt_sha256": sha256_file(source / "source-receipt.json")[0],
        "auditor_sha256": sha256_file(Path(__file__))[0],
        "native_response_bindings": page_bindings,
        "native_denominators": denominators,
        "native_url_entities": len(seen_urls),
        "resolved": {kind: len(saved[kind]["resolved"]) for kind in url_ids},
        "ambiguous_native_urls": ambiguous_native_urls,
        "raw_native_member_reconstruction": True,
        "musical_equivalence_claimed": False,
        "transport_receipt_validation": "separate bridge verifier; this auditor checks bytes",
    }


def main() -> None:
    """Write fresh independent evidence without altering captures or production data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source, args.pack)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
