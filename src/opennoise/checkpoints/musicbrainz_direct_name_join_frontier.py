"""Report exact-MBID name coverage for the local direct-genre frontier.

This is a local accounting join only.  Direct source claims and canonical name
facts remain separate inputs; it neither creates memberships nor writes a
static asset.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.musicbrainz_direct_discovery_delta import (
    build_musicbrainz_direct_discovery_delta,
)
from opennoise.deployment.musicbrainz_direct_artist_name_recovery import (
    DirectArtistNameRecoveryReceipt,
    iter_verified_unique_recovered_names,
)
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
    iter_verified_direct_canonical_artist_names,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.models import FrozenModel

_SHA256: Final = "^[0-9a-f]{64}$"


class DirectNameJoinFrontierError(ValueError):
    """The requested exact-ID accounting join is not custody-bound."""


class PerSeedNameCoverage(FrozenModel):
    """Coverage counts over distinct exact ``(seed_id, artist_mbid)`` pairs."""

    seed_id: str = Field(min_length=1)
    direct_artist_pair_count: int = Field(ge=0)
    named_direct_artist_pair_count: int = Field(ge=0)
    unnamed_direct_artist_pair_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _coverage_partitions_pairs(self) -> PerSeedNameCoverage:
        if self.named_direct_artist_pair_count + self.unnamed_direct_artist_pair_count != (
            self.direct_artist_pair_count
        ):
            raise ValueError("named and unnamed counts must partition direct artist pairs")
        return self


class DirectNameJoinFrontierReport(FrozenModel):
    """A bounded local-only coverage report, never a proposed payload itself."""

    revision: Literal["musicbrainz-direct-name-join-frontier-v1"] = (
        "musicbrainz-direct-name-join-frontier-v1"
    )
    publication_scope: Literal["local_review_only"] = "local_review_only"
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    release_gate: Literal[False] = False
    inputs: dict[str, str]
    candidate_only_seed_count: int = Field(ge=0)
    candidate_only_direct_artist_pair_count: int = Field(ge=0)
    candidate_only_named_direct_artist_pair_count: int = Field(ge=0)
    candidate_only_unnamed_direct_artist_pair_count: int = Field(ge=0)
    candidate_only_exact_display_coverage: float = Field(ge=0, le=1)
    candidate_only_per_seed: tuple[PerSeedNameCoverage, ...]
    proposed_static_payload: dict[str, object]

    @model_validator(mode="after")
    def _report_is_complete_and_local(self) -> DirectNameJoinFrontierReport:
        if self.public_export_authorized or self.serving_authorized or self.release_gate:
            raise ValueError("name join frontier must remain local-only")
        if (
            self.candidate_only_named_direct_artist_pair_count
            + self.candidate_only_unnamed_direct_artist_pair_count
            != (self.candidate_only_direct_artist_pair_count)
        ):
            raise ValueError("candidate-only coverage must partition direct artist pairs")
        if len(self.candidate_only_per_seed) != self.candidate_only_seed_count:
            raise ValueError("per-seed rows must cover every candidate-only seed")
        if (
            sum(row.direct_artist_pair_count for row in self.candidate_only_per_seed),
            sum(row.named_direct_artist_pair_count for row in self.candidate_only_per_seed),
            sum(row.unnamed_direct_artist_pair_count for row in self.candidate_only_per_seed),
        ) != (
            self.candidate_only_direct_artist_pair_count,
            self.candidate_only_named_direct_artist_pair_count,
            self.candidate_only_unnamed_direct_artist_pair_count,
        ):
            raise ValueError("per-seed coverage must equal candidate-only totals")
        expected_coverage = (
            0
            if self.candidate_only_direct_artist_pair_count == 0
            else self.candidate_only_named_direct_artist_pair_count
            / self.candidate_only_direct_artist_pair_count
        )
        if self.candidate_only_exact_display_coverage != expected_coverage:
            raise ValueError("exact display coverage must replay from candidate-only pair totals")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_direct_receipt(path: Path, *, expected_sha256: str) -> DirectProperGenreCustodyReceipt:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise DirectNameJoinFrontierError(
            "direct custody receipt bytes do not match expected SHA-256"
        )
    try:
        return DirectProperGenreCustodyReceipt.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise DirectNameJoinFrontierError("direct custody receipt is invalid") from error


def _load_name_receipt(
    path: Path, *, expected_sha256: str
) -> DirectCanonicalArtistNameCustodyReceipt:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise DirectNameJoinFrontierError(
            "name custody receipt bytes do not match expected SHA-256"
        )
    try:
        return DirectCanonicalArtistNameCustodyReceipt.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise DirectNameJoinFrontierError("name custody receipt is invalid") from error


def _load_recovery_receipt(path: Path, *, expected_sha256: str) -> DirectArtistNameRecoveryReceipt:
    if _sha256(path) != expected_sha256:
        raise DirectNameJoinFrontierError("recovery receipt bytes do not match expected SHA-256")
    try:
        return DirectArtistNameRecoveryReceipt.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise DirectNameJoinFrontierError("recovery receipt is invalid") from error


def _optional_recovery_inputs(
    *,
    recovery_receipt_path: Path | None,
    recovery_receipt_sha256: str | None,
    recovery_object_store: Path | None,
) -> tuple[Path, str, Path] | None:
    inputs = (recovery_receipt_path, recovery_receipt_sha256, recovery_object_store)
    if all(value is None for value in inputs):
        return None
    if any(value is None for value in inputs):
        raise DirectNameJoinFrontierError(
            "recovery receipt, receipt SHA-256, and object store must be supplied together"
        )
    path, receipt_sha256, object_store = inputs
    if (
        not isinstance(path, Path)
        or not isinstance(receipt_sha256, str)
        or not isinstance(object_store, Path)
    ):
        raise DirectNameJoinFrontierError("recovery inputs have invalid types")
    return path, receipt_sha256, object_store


def build_musicbrainz_direct_name_join_frontier(  # noqa: PLR0913 - explicit custody inputs.
    *,
    direct_custody_receipt_path: Path,
    direct_custody_receipt_sha256: str,
    direct_object_store: Path,
    name_custody_receipt_path: Path,
    name_custody_receipt_sha256: str,
    name_object_store: Path,
    static_discovery_path: Path,
    certified_manifest_path: Path,
    certified_layout_path: Path,
    recovery_receipt_path: Path | None = None,
    recovery_receipt_sha256: str | None = None,
    recovery_object_store: Path | None = None,
) -> DirectNameJoinFrontierReport:
    """Build a deterministic exact-MBID coverage report for candidate-only seeds."""
    direct_receipt = _load_direct_receipt(
        direct_custody_receipt_path, expected_sha256=direct_custody_receipt_sha256
    )
    name_receipt = _load_name_receipt(
        name_custody_receipt_path, expected_sha256=name_custody_receipt_sha256
    )
    if (
        name_receipt.direct_custody_receipt_byte_sha256,
        name_receipt.direct_custody_receipt_output_sha256,
        name_receipt.direct_claims_object_sha256,
    ) != (
        direct_custody_receipt_sha256,
        direct_receipt.output_sha256,
        direct_receipt.claims_object_sha256,
    ):
        raise DirectNameJoinFrontierError(
            "name custody receipt is bound to a different direct cohort"
        )
    recovery_inputs = _optional_recovery_inputs(
        recovery_receipt_path=recovery_receipt_path,
        recovery_receipt_sha256=recovery_receipt_sha256,
        recovery_object_store=recovery_object_store,
    )
    recovery_receipt: DirectArtistNameRecoveryReceipt | None = None
    if recovery_inputs is not None:
        recovery_path, recovery_byte_sha256, _ = recovery_inputs
        recovery_receipt = _load_recovery_receipt(
            recovery_path, expected_sha256=recovery_byte_sha256
        )
        if (
            recovery_receipt.direct_custody_receipt_byte_sha256,
            recovery_receipt.direct_custody_receipt_output_sha256,
            recovery_receipt.direct_claims_object_sha256,
            recovery_receipt.name_custody_receipt_byte_sha256,
            recovery_receipt.name_custody_receipt_output_sha256,
            recovery_receipt.name_custody_object_sha256,
        ) != (
            direct_custody_receipt_sha256,
            direct_receipt.output_sha256,
            direct_receipt.claims_object_sha256,
            name_custody_receipt_sha256,
            name_receipt.output_sha256,
            name_receipt.names_object_sha256,
        ):
            raise DirectNameJoinFrontierError(
                "recovery receipt is bound to a different direct or canonical-name cohort"
            )

    delta = build_musicbrainz_direct_discovery_delta(
        custody_receipt_path=direct_custody_receipt_path,
        custody_object_store=direct_object_store,
        static_discovery_path=static_discovery_path,
        certified_manifest_path=certified_manifest_path,
        certified_layout_path=certified_layout_path,
    )
    candidate_rows = delta["candidate_only_per_seed"]
    if not isinstance(candidate_rows, tuple):
        raise DirectNameJoinFrontierError(
            "certified delta has no deterministic candidate seed rows"
        )
    candidate_ids = frozenset(
        row["seed_id"] for row in candidate_rows if isinstance(row.get("seed_id"), str)
    )
    if len(candidate_ids) != len(candidate_rows):
        raise DirectNameJoinFrontierError("certified delta has invalid candidate seed rows")

    with tempfile.TemporaryDirectory(prefix="musicbrainz-direct-name-join-") as directory:
        connection = sqlite3.connect(Path(directory) / "join.sqlite")
        connection.row_factory = sqlite3.Row
        try:
            _stream_exact_join_inputs(
                connection,
                direct_receipt=direct_receipt,
                direct_object_store=direct_object_store,
                name_receipt=name_receipt,
                name_object_store=name_object_store,
                recovery_receipt=recovery_receipt,
                recovery_object_store=None if recovery_inputs is None else recovery_inputs[2],
                candidate_ids=candidate_ids,
            )
            per_seed, totals, payload = _report_from_join(connection, candidate_ids=candidate_ids)
        finally:
            connection.close()
    total, named, unnamed = totals
    inputs = {
        "direct_custody_receipt_byte_sha256": direct_custody_receipt_sha256,
        "direct_custody_receipt_output_sha256": direct_receipt.output_sha256,
        "direct_claims_object_sha256": direct_receipt.claims_object_sha256,
        "name_custody_receipt_byte_sha256": name_custody_receipt_sha256,
        "name_custody_receipt_output_sha256": name_receipt.output_sha256,
        "names_object_sha256": name_receipt.names_object_sha256,
    }
    if recovery_receipt is not None and recovery_inputs is not None:
        inputs.update(
            {
                "recovery_receipt_byte_sha256": recovery_inputs[1],
                "recovery_receipt_output_sha256": recovery_receipt.output_sha256,
                "recovery_object_sha256": recovery_receipt.recovery_object_sha256,
            }
        )
    return DirectNameJoinFrontierReport(
        inputs=inputs,
        candidate_only_seed_count=len(candidate_ids),
        candidate_only_direct_artist_pair_count=total,
        candidate_only_named_direct_artist_pair_count=named,
        candidate_only_unnamed_direct_artist_pair_count=unnamed,
        candidate_only_exact_display_coverage=0 if total == 0 else named / total,
        candidate_only_per_seed=per_seed,
        proposed_static_payload=payload,
    )


def _stream_exact_join_inputs(  # noqa: PLR0913 - separate custody inputs are intentional.
    connection: sqlite3.Connection,
    *,
    direct_receipt: DirectProperGenreCustodyReceipt,
    direct_object_store: Path,
    name_receipt: DirectCanonicalArtistNameCustodyReceipt,
    name_object_store: Path,
    recovery_receipt: DirectArtistNameRecoveryReceipt | None,
    recovery_object_store: Path | None,
    candidate_ids: frozenset[str],
) -> None:
    connection.executescript(
        """
        CREATE TABLE direct_pairs (
            seed_id TEXT NOT NULL,
            artist_mbid TEXT NOT NULL,
            PRIMARY KEY (seed_id, artist_mbid)
        ) WITHOUT ROWID;
        CREATE TABLE canonical_name_facts (
            artist_mbid TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )
    try:
        for claim in iter_verified_portable_direct_proper_genre_claims(
            direct_receipt, object_store=direct_object_store
        ):
            if claim.seed_id in candidate_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO direct_pairs VALUES (?, ?)",
                    (claim.seed_id, claim.artist_mbid),
                )
    except (OSError, ValueError, RuntimeError) as error:
        raise DirectNameJoinFrontierError("direct custody object did not verify") from error
    try:
        for name in iter_verified_direct_canonical_artist_names(
            name_receipt, object_store=name_object_store
        ):
            connection.execute(
                "INSERT INTO canonical_name_facts VALUES (?, ?)",
                (name.artist_mbid, name.canonical_name),
            )
        if recovery_receipt is not None:
            if recovery_object_store is None:
                raise DirectNameJoinFrontierError("recovery object store is missing")
            for name in iter_verified_unique_recovered_names(
                recovery_receipt, object_store=recovery_object_store
            ):
                connection.execute(
                    "INSERT INTO canonical_name_facts VALUES (?, ?)",
                    (name.artist_mbid, name.canonical_name),
                )
    except sqlite3.IntegrityError as error:
        raise DirectNameJoinFrontierError(
            "recovered name repeats a canonical-name custody MBID"
        ) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise DirectNameJoinFrontierError(
            "canonical or recovery name object did not verify"
        ) from error


def _report_from_join(
    connection: sqlite3.Connection, *, candidate_ids: frozenset[str]
) -> tuple[tuple[PerSeedNameCoverage, ...], tuple[int, int, int], dict[str, object]]:
    rows = connection.execute(
        """
        SELECT direct_pairs.seed_id,
               COUNT(*) AS pair_count,
               SUM(canonical_name_facts.artist_mbid IS NOT NULL) AS named_pair_count
        FROM direct_pairs
        LEFT JOIN canonical_name_facts USING (artist_mbid)
        GROUP BY direct_pairs.seed_id
        ORDER BY direct_pairs.seed_id
        """
    ).fetchall()
    found_ids = frozenset(str(row["seed_id"]) for row in rows)
    if found_ids != candidate_ids:
        raise DirectNameJoinFrontierError("candidate seed has no exact direct artist pairs")
    per_seed = tuple(
        PerSeedNameCoverage(
            seed_id=str(row["seed_id"]),
            direct_artist_pair_count=int(row["pair_count"]),
            named_direct_artist_pair_count=int(row["named_pair_count"]),
            unnamed_direct_artist_pair_count=int(row["pair_count"]) - int(row["named_pair_count"]),
        )
        for row in rows
    )
    total = sum(row.direct_artist_pair_count for row in per_seed)
    named = sum(row.named_direct_artist_pair_count for row in per_seed)
    unnamed = total - named
    payload_bytes = sum(
        len(
            json.dumps(
                {"artist_mbid": mbid, "canonical_name": name, "seed_id": seed},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        + 1
        for seed, mbid, name in connection.execute(
            """
            SELECT direct_pairs.seed_id, direct_pairs.artist_mbid,
                   canonical_name_facts.canonical_name
            FROM direct_pairs JOIN canonical_name_facts USING (artist_mbid)
            ORDER BY direct_pairs.seed_id, direct_pairs.artist_mbid
            """
        )
    )
    payload = {
        "status": "derived_local_estimate",
        "public_asset_written": False,
        "scope": "uncompressed_minimal_candidate_shape_not_a_production_asset",
        "format": "canonical_jsonl",
        "row_count": named,
        "fields": ("artist_mbid", "canonical_name", "seed_id"),
        "serialized_byte_size": payload_bytes,
        "excludes": (
            "source_claim_fields",
            "unnamed_pairs",
            "membership_or_similarity_inference",
        ),
    }
    return per_seed, (total, named, unnamed), payload


def report_json(report: DirectNameJoinFrontierReport) -> str:
    """Serialize the local-only report deterministically."""
    return json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
