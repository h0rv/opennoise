"""Cross-cutting, fail-closed application policies."""

from opennoise.policy.content import (
    AudioContentRejectedError,
    require_metadata_file,
    require_metadata_media_type,
    require_metadata_path,
    require_metadata_prefix,
    require_metadata_url,
)

__all__ = [
    "AudioContentRejectedError",
    "require_metadata_file",
    "require_metadata_media_type",
    "require_metadata_path",
    "require_metadata_prefix",
    "require_metadata_url",
]
