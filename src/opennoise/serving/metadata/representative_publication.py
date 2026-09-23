"""Publish one verified metadata-example artifact through the generic object-store boundary."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field, ValidationError

from opennoise.models import FrozenModel
from opennoise.policy import require_metadata_file
from opennoise.serving.metadata.representatives import (
    MetadataRepresentativeArtifact,
    RepresentativeRunProvenance,
    metadata_representatives,
)
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from pathlib import Path

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_METADATA_PROVENANCE_PREFIX = "catalog:metadata:"


class MetadataRepresentativePublicationError(RuntimeError):
    """Report an artifact that cannot be safely persisted as public metadata."""


class LoadedMetadataRepresentativeArtifact(FrozenModel):
    """Carry the parsed artifact with its exact file identity."""

    artifact: MetadataRepresentativeArtifact
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=MAX_ARTIFACT_BYTES)


class MetadataRepresentativePublication(FrozenModel):
    """Receipt for one immutable, metadata-only representative publication."""

    revision: Literal["metadata-representative-publication-v1"] = (
        "metadata-representative-publication-v1"
    )
    artifact: ObjectWrite
    run: RepresentativeRunProvenance
    total_examples: int = Field(gt=0)
    release_group_examples: int = Field(ge=0)
    recording_examples: int = Field(ge=0)
    release_group_genres: int = Field(ge=0)
    recording_genres: int = Field(ge=0)
    recording_semantics: str
    content_policy: Literal["metadata_only_no_audio_or_preview_urls"] = (
        "metadata_only_no_audio_or_preview_urls"
    )


def load_metadata_representative_artifact(path: Path) -> LoadedMetadataRepresentativeArtifact:
    """Parse one bounded JSON artifact and reject media before publication."""
    absolute = path.resolve(strict=True)
    try:
        require_metadata_file(absolute)
    except ValueError as error:
        raise MetadataRepresentativePublicationError(
            "metadata representative artifact violates the no-media policy"
        ) from error
    with absolute.open("rb") as stream:
        payload = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise MetadataRepresentativePublicationError(
            "metadata representative artifact exceeds the 8 MiB limit"
        )
    if not payload:
        raise MetadataRepresentativePublicationError("metadata representative artifact is empty")
    try:
        artifact = MetadataRepresentativeArtifact.model_validate_json(payload)
    except (ValidationError, ValueError) as error:
        raise MetadataRepresentativePublicationError(
            "metadata representative artifact is invalid"
        ) from error
    return LoadedMetadataRepresentativeArtifact(
        artifact=artifact,
        file_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )


def verify_metadata_representative_publication_policy(
    artifact: MetadataRepresentativeArtifact, catalog_database: Path
) -> None:
    """Bind examples to catalog selections and require display/export authorization.

    The artifact's evidence references identify the source assertion that binds a
    recording or release group to a genre.  A model run being exportable does not
    supersede that source policy, so this check belongs immediately before the
    object-store publication boundary.
    """
    try:
        selected = metadata_representatives(catalog_database)
    except (OSError, RuntimeError, ValueError) as error:
        raise MetadataRepresentativePublicationError(
            "catalog database cannot reconstruct metadata representative selection"
        ) from error
    if artifact != selected:
        raise MetadataRepresentativePublicationError(
            "metadata representative artifact does not exactly match catalog selection"
        )
    provenance_ids = tuple(
        sorted(
            {
                _metadata_provenance_id(reference)
                for item in artifact.items
                for reference in item.evidence_refs
            }
        )
    )
    absolute = catalog_database.resolve(strict=True)
    try:
        with closing(
            sqlite3.connect(f"file:{absolute.as_posix()}?mode=ro", uri=True)
        ) as connection:
            for provenance_id in provenance_ids:
                permitted = connection.execute(
                    """SELECT EXISTS(
                           SELECT 1
                           FROM provenance_records AS provenance
                           JOIN active_rights_policy_permissions AS display_permission
                             ON display_permission.policy_id = provenance.policy_id
                            AND display_permission.use_kind = 'display'
                            AND display_permission.decision = 'allow'
                           JOIN active_rights_policy_permissions AS export_permission
                             ON export_permission.policy_id = provenance.policy_id
                            AND export_permission.use_kind = 'export'
                            AND export_permission.decision = 'allow'
                           WHERE provenance.id = ?
                       )""",
                    (provenance_id,),
                ).fetchone()
                if permitted is None or int(permitted[0]) != 1:
                    raise MetadataRepresentativePublicationError(
                        "metadata representative evidence is not actively authorized "
                        f"for display and export: {provenance_id}"
                    )
    except sqlite3.Error as error:
        raise MetadataRepresentativePublicationError(
            "catalog database cannot verify metadata representative policy"
        ) from error


def _metadata_provenance_id(reference: str) -> int:
    """Parse the sole provenance-reference form accepted at public publication."""
    raw_id = reference.removeprefix(_METADATA_PROVENANCE_PREFIX)
    if raw_id == reference or not raw_id.isdecimal() or int(raw_id) <= 0:
        raise MetadataRepresentativePublicationError(
            f"metadata representative has an invalid provenance reference: {reference}"
        )
    return int(raw_id)


def publish_metadata_representatives(
    artifact_path: Path,
    store: ObjectStore,
    catalog_database: Path,
) -> MetadataRepresentativePublication:
    """Persist a verified selection artifact without re-ranking, fetching, or reading media."""
    loaded = load_metadata_representative_artifact(artifact_path)
    verify_metadata_representative_publication_policy(loaded.artifact, catalog_database)
    key = ObjectKey(value=f"metadata-representatives/sha256/{loaded.file_sha256}.json")
    stored = store.push(artifact_path, key)
    if (stored.sha256, stored.byte_size) != (loaded.file_sha256, loaded.byte_size):
        raise MetadataRepresentativePublicationError("object store changed representative artifact")
    items = loaded.artifact.items
    release_groups = tuple(item for item in items if item.entity_kind == "release_group")
    recordings = tuple(item for item in items if item.entity_kind == "recording")
    return MetadataRepresentativePublication(
        artifact=stored,
        run=loaded.artifact.run,
        total_examples=len(items),
        release_group_examples=len(release_groups),
        recording_examples=len(recordings),
        release_group_genres=len({item.genre_id for item in release_groups}),
        recording_genres=len({item.genre_id for item in recordings}),
        recording_semantics=loaded.artifact.recording_semantics,
    )
