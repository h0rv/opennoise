"""Build the bounded local MusicBrainz entity genre observation report."""

from __future__ import annotations

from pathlib import Path

from opennoise.ingest.musicbrainz.entity_genre_observation import (
    BOUNDED_ENTITY_GENRE_RECEIPTS,
    EntityGenreSourceReceipt,
    RetainedEntityGenreResponse,
    build_entity_genre_observation_report,
    verify_entity_genre_observation_report,
    write_local_report_once,
)

_ROOT = Path(".cache/musicbrainz-entity-genre-observation-v1")
_RESPONSES = _ROOT / "responses"
_OUTPUT = _ROOT / "report.json"


def _retained_response(receipt: EntityGenreSourceReceipt) -> RetainedEntityGenreResponse:
    api_kind = receipt.entity_kind.replace("_", "-")
    path = _RESPONSES / f"{api_kind}-{receipt.entity_mbid}.json"
    payload = path.read_bytes()
    return RetainedEntityGenreResponse(receipt=receipt, payload=payload)


def main() -> int:
    """Replay ten retained entity responses into a hash-checked local report."""
    report = build_entity_genre_observation_report(
        tuple(_retained_response(receipt) for receipt in BOUNDED_ENTITY_GENRE_RECEIPTS)
    )
    verify_entity_genre_observation_report(report)
    write_local_report_once(
        cache_root=_ROOT,
        output=_OUTPUT,
        payload=(report.model_dump_json() + "\n").encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
