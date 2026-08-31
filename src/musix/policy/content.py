"""Reject audio and stream payloads before Musix reads or stores them."""

from pathlib import Path, PurePath
from urllib.parse import urlparse

SNIFF_BYTES = 16
CONTAINER_HEADER_BYTES = 12
FRAME_HEADER_BYTES = 2
FRAME_SYNC_BYTE = 0xFF
FRAME_SYNC_MASK = 0xF0

_FORBIDDEN_MEDIA_PREFIXES = ("audio/", "video/")
_FORBIDDEN_MEDIA_TYPES = frozenset(
    {
        "application/ogg",
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
    }
)
_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
        ".alac",
        ".flac",
        ".m3u",
        ".m3u8",
        ".m4a",
        ".mid",
        ".midi",
        ".mp3",
        ".mp4",
        ".oga",
        ".ogg",
        ".opus",
        ".pls",
        ".wav",
        ".weba",
        ".webm",
        ".wma",
    }
)


class AudioContentRejectedError(ValueError):
    """Report audio, music, preview, or stream bytes at a metadata boundary."""


def require_metadata_media_type(media_type: str) -> None:
    """Reject media types that can carry audio or an audio stream."""
    normalized = media_type.partition(";")[0].strip().casefold()
    if normalized in _FORBIDDEN_MEDIA_TYPES or normalized.startswith(_FORBIDDEN_MEDIA_PREFIXES):
        raise AudioContentRejectedError("Musix accepts metadata artifacts only, never media bytes")


def require_metadata_path(path: str | PurePath) -> None:
    """Reject filenames and archive members that identify media or stream payloads."""
    suffix = PurePath(str(path)).suffix.casefold()
    if suffix in _FORBIDDEN_SUFFIXES:
        raise AudioContentRejectedError(f"Musix rejected media payload path {str(path)!r}")


def require_metadata_url(url: str) -> None:
    """Reject acquisition URLs for media or stream payloads."""
    require_metadata_path(urlparse(url).path)


def require_metadata_prefix(prefix: bytes) -> None:
    """Reject common audio container signatures without decoding the payload."""
    is_riff_audio = (
        len(prefix) >= CONTAINER_HEADER_BYTES
        and prefix.startswith(b"RIFF")
        and prefix[8:12] == b"WAVE"
    )
    is_aiff = (
        len(prefix) >= CONTAINER_HEADER_BYTES
        and prefix.startswith(b"FORM")
        and prefix[8:12]
        in {
            b"AIFF",
            b"AIFC",
        }
    )
    is_iso_media = len(prefix) >= CONTAINER_HEADER_BYTES and prefix[4:8] == b"ftyp"
    is_mpeg_or_adts = (
        len(prefix) >= FRAME_HEADER_BYTES
        and prefix[0] == FRAME_SYNC_BYTE
        and prefix[1] & FRAME_SYNC_MASK == FRAME_SYNC_MASK
    )
    if (
        prefix.startswith((b"ID3", b"fLaC", b"OggS", b"MThd"))
        or is_riff_audio
        or is_aiff
        or is_iso_media
        or is_mpeg_or_adts
    ):
        raise AudioContentRejectedError("Musix rejected an audio or media byte signature")


def require_metadata_file(path: Path) -> None:
    """Check a local artifact path and prefix before parsing or storage."""
    require_metadata_path(path)
    with path.open("rb") as stream:
        require_metadata_prefix(stream.read(SNIFF_BYTES))
