"""Stable, compact source-artifact identities for aggregate artist-pair evidence."""

from collections.abc import Iterable

from opennoise.common import sha256_json

type ArtistPairSourceArtifactIdentity = tuple[str, str, str]

_V3_PREFIX = "lb:v3:"


def artist_pair_source_artifact_ref_v3(
    source_key: str, snapshot_ref: str, artifact_sha256: str
) -> str:
    """Hash one canonical source/snapshot/artifact identity into a compact reference."""
    return f"{_V3_PREFIX}{sha256_json([source_key, snapshot_ref, artifact_sha256])}"


def resolve_artist_pair_source_artifact_ref_v3(
    reference: str, identities: Iterable[ArtistPairSourceArtifactIdentity]
) -> ArtistPairSourceArtifactIdentity:
    """Resolve a v3 token against an attested inventory, rejecting ambiguity."""
    if not reference.startswith(_V3_PREFIX):
        raise ValueError("artist pair evidence reference is not an lb:v3 token")
    matches = {
        identity
        for identity in identities
        if artist_pair_source_artifact_ref_v3(*identity) == reference
    }
    if not matches:
        raise ValueError("artist pair evidence reference is outside the attested inventory")
    if len(matches) != 1:
        raise ValueError("artist pair evidence reference is ambiguous in the attested inventory")
    return matches.pop()
