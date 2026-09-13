"""Publish one verified metadata-example artifact through the generic object-store boundary."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import Field, ValidationError

from opennoise.models import FrozenModel
from opennoise.policy import require_metadata_file
from opennoise.serving.metadata.representatives import (
    MetadataRepresentativeArtifact,
    RepresentativeRunProvenance,
)
from opennoise.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from pathlib import Path

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


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


def publish_metadata_representatives(
    artifact_path: Path,
    store: ObjectStore,
) -> MetadataRepresentativePublication:
    """Persist a verified selection artifact without re-ranking, fetching, or reading media."""
    loaded = load_metadata_representative_artifact(artifact_path)
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
