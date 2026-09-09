"""Startup-verified reviewed-alias context for local discovery only."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field

from musix.ingest.musicbrainz.reviewed_alias_context import (
    ReviewedAliasCombinedModelReceipt,
    ReviewedAliasContextArtifact,
    ReviewedAliasContextError,
    verify_reviewed_alias_combined_model_receipt,
    verify_reviewed_alias_context_artifact,
)
from musix.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

    from musix.ingest.musicbrainz.model_adapter import MusicBrainzModelAdapterReport
    from musix.taxonomy.seeds.reconciliation import SeedReconciliationArtifact


_REVIEWED_ALIAS_PEER_INDEX_ARTIFACT_SHA256 = (
    "201a5061c2bcd0b71e7d6ac867e8a42d76b3c8cfed0318d88752cfbae12853eb"
)


class LocalReviewedAliasContextStoreError(ValueError):
    """Report invalid local reviewed-alias context inputs."""


class LocalReviewedAliasArtistRow(FrozenModel):
    """One reviewed tag observation rendered alongside direct artist claims."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_record_id: str = Field(min_length=1)
    contextual_evidence_ref: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)


class LocalReviewedAliasSeedRow(FrozenModel):
    """One reviewed tag observation rendered alongside direct seed claims."""

    source_item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    contextual_evidence_ref: str = Field(min_length=1)
    approval_ref: str = Field(min_length=1)


@dataclass(slots=True)
class LocalReviewedAliasContextStore:
    """Keep the small, approved context overlay separate from direct evidence."""

    artifact_path: Path
    receipt_path: Path
    peer_index_path: Path
    adapter_report: MusicBrainzModelAdapterReport
    reconciliation: SeedReconciliationArtifact
    _by_seed: dict[str, tuple[LocalReviewedAliasArtistRow, ...]] | None = None
    _by_artist: dict[str, tuple[LocalReviewedAliasSeedRow, ...]] | None = None

    def start(self) -> None:
        """Verify receipt lineage and materialize only the bounded context rows."""
        try:
            artifact = ReviewedAliasContextArtifact.model_validate_json(
                self.artifact_path.read_bytes()
            )
            receipt = ReviewedAliasCombinedModelReceipt.model_validate_json(
                self.receipt_path.read_bytes()
            )
            verify_reviewed_alias_context_artifact(artifact)
            verify_reviewed_alias_combined_model_receipt(receipt)
        except (OSError, ValueError, ReviewedAliasContextError) as error:
            raise LocalReviewedAliasContextStoreError(
                "reviewed alias context is invalid"
            ) from error
        if (
            artifact.output_sha256 != receipt.reviewed_alias_context_output_sha256
            or artifact.baseline_output_sha256 != self.adapter_report.seed_target_output_sha256
            or receipt.baseline_seed_target_output_sha256
            != self.adapter_report.seed_target_output_sha256
        ):
            raise LocalReviewedAliasContextStoreError("reviewed alias context binding is invalid")
        self._verify_matching_peer_index()
        seed_names = {row.source_item_id: row.seed_name for row in self.reconciliation.dispositions}
        by_seed: dict[str, list[LocalReviewedAliasArtistRow]] = {}
        by_artist: dict[str, list[LocalReviewedAliasSeedRow]] = {}
        for row in artifact.memberships:
            seed_name = seed_names.get(row.seed_source_item_id)
            if seed_name is None:
                raise LocalReviewedAliasContextStoreError(
                    "reviewed alias context has an unknown stable seed"
                )
            by_seed.setdefault(row.seed_source_item_id, []).append(
                LocalReviewedAliasArtistRow(
                    artist_mbid=row.artist_id,
                    source_record_id=row.source_record_id,
                    contextual_evidence_ref=row.contextual_evidence_ref,
                    approval_ref=row.approval_ref,
                )
            )
            by_artist.setdefault(row.artist_id, []).append(
                LocalReviewedAliasSeedRow(
                    source_item_id=row.seed_source_item_id,
                    name=seed_name,
                    source_record_id=row.source_record_id,
                    contextual_evidence_ref=row.contextual_evidence_ref,
                    approval_ref=row.approval_ref,
                )
            )
        self._by_seed = {
            key: tuple(sorted(value, key=lambda item: item.artist_mbid))
            for key, value in by_seed.items()
        }
        self._by_artist = {
            key: tuple(sorted(value, key=lambda item: item.source_item_id))
            for key, value in by_artist.items()
        }

    @property
    def configured(self) -> bool:
        """Whether the verified overlay is available."""
        return self._by_seed is not None

    def artist_rows(self, seed_id: str) -> tuple[LocalReviewedAliasArtistRow, ...]:
        """Return approved contextual artist rows for one exact seed."""
        if self._by_seed is None:
            raise LocalReviewedAliasContextStoreError("reviewed alias context is not certified")
        return self._by_seed.get(seed_id, ())

    def seed_rows(self, artist_id: str) -> tuple[LocalReviewedAliasSeedRow, ...]:
        """Return approved contextual seed rows for one exact artist."""
        if self._by_artist is None:
            raise LocalReviewedAliasContextStoreError("reviewed alias context is not certified")
        return self._by_artist.get(artist_id, ())

    def _verify_matching_peer_index(self) -> None:
        """Require the peer view to come from the receipt's reviewed candidate."""
        if not self.peer_index_path.is_file() or self.peer_index_path.suffix == ".partial":
            raise LocalReviewedAliasContextStoreError("reviewed alias peer index is unavailable")
        database_uri = f"file:{self.peer_index_path.absolute()}?mode=ro"
        try:
            with closing(sqlite3.connect(database_uri, uri=True)) as connection:
                connection.execute("PRAGMA query_only = ON")
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise LocalReviewedAliasContextStoreError(
                        "reviewed alias peer index failed integrity check"
                    )
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        except sqlite3.Error as error:
            raise LocalReviewedAliasContextStoreError(
                "reviewed alias peer index is invalid"
            ) from error
        if metadata.get("artifact_output_sha256") != _REVIEWED_ALIAS_PEER_INDEX_ARTIFACT_SHA256:
            raise LocalReviewedAliasContextStoreError(
                "reviewed alias peer index does not match the combined candidate"
            )
