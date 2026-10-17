"""Pre-fit compatibility and identity yield from pinned native CC0 responses."""

from collections import Counter
from pathlib import Path
from typing import Any

from opennoise.ml import ab178_portable as portable


def inventory(
    source: Path, source_pin: str, contract_path: Path, contract_pin: str
) -> dict[str, Any]:
    """Replay approved custody and classify all nominations without fitting or ranking."""
    if portable.bank.digest(source / "receipt.json") != source_pin:
        raise ValueError("Native input receipt differs from external pin")
    feature_contract = portable.contract(portable.read(contract_path, contract_pin))
    rows = portable.source_rows(source, feature_contract)
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["version"] is None:
            continue
        candidate = {
            "revision": portable.CONTRACT_REVISION,
            "schema_sha256": portable.hash_value(portable.bank.columns()),
            "version": row["version"],
            "analysis": row["analysis"],
        }
        try:
            portable.contract(candidate)
        except (ValueError, TypeError):
            continue
        key = portable.hash_value(candidate)
        group = groups.setdefault(key, {"contract": candidate, "recording_mbids": []})
        if row["evidence"]["identity_state"] == "matched" and row["credited_artist_mbids"]:
            group["recording_mbids"].append(row["recording_mbid"])
    joined = [row for row in rows if row["join_state"] == "joined"]
    return {
        "revision": "native-ab178-prefit-inventory-v1",
        "source_receipt_sha256": source_pin,
        "contract_sha256": contract_pin,
        "producer_sha256": portable.bank.digest(Path(__file__)),
        "dependencies": {
            "portable": portable.bank.digest(Path(portable.__file__)),
            "bank": portable.bank.digest(Path(portable.bank.__file__)),
        },
        "scope": {"fit": False, "network": False, "musical_validation": False},
        "nominated_recordings": len(rows),
        "state_counts": dict(sorted(Counter(row["join_state"] for row in rows).items())),
        "compatible_coordinate_observation_counts": [
            sum(not row["missing_mask"][index] for row in joined)
            for index in range(len(portable.bank.columns()))
        ],
        "clean_identity_verified_cohorts": dict(sorted(groups.items())),
        "records": [
            {
                key: row[key]
                for key in (
                    "recording_mbid",
                    "join_state",
                    "credited_artist_mbids",
                    "version",
                    "analysis",
                )
            }
            for row in rows
        ],
    }
