"""Render a local-only HTML preview from the verified credit-detail seam.

The deployed static page exporter does not import this module.  It creates a
new directory below a caller-selected local ``.cache`` root and writes only a
source-bound JSON sidecar and a no-JavaScript HTML preview there.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Final

from opennoise.deployment.musicbrainz_credit_artist_detail_local import (
    LocalMusicBrainzCreditArtistDetailError,
    LocalMusicBrainzCreditArtistDetailPayload,
    export_local_musicbrainz_credit_artist_detail_payload,
)
from opennoise.deployment.musicbrainz_credit_static_export import (
    CreditMetadataPublicationApproval,
    MusicBrainzCreditStaticMetadataPayload,
)

if TYPE_CHECKING:
    from opennoise.deployment.musicbrainz_credit_static_export import (
        MusicBrainzCreditMetadataRow,
    )

_STATIC_ROOT: Final = Path(__file__).resolve().parents[1] / "static"
_REPOSITORY_DIST: Final = Path(__file__).resolve().parents[3] / "dist"


@dataclass(frozen=True, slots=True)
class LocalMusicBrainzCreditArtistDetailHtmlPreview:
    """Paths and hashes for one non-public, static artist-detail preview."""

    payload: LocalMusicBrainzCreditArtistDetailPayload
    payload_sha256: str
    directory: Path
    html_path: Path
    payload_path: Path


def export_local_musicbrainz_credit_artist_detail_html_preview(  # noqa: PLR0913 - explicit gate inputs.
    *,
    credit_metadata: Path,
    approval: Path,
    static_discovery: Path,
    static_artist_id: str,
    local_root: Path,
    output_directory: Path,
) -> LocalMusicBrainzCreditArtistDetailHtmlPreview:
    """Write one local HTML view after replaying approval, policy, and ID gates.

    The JSON sidecar is produced by the existing renderer. A separately stored
    approval must bind its candidate, public database, static-discovery, and
    credit-artifact hashes to the resulting payload. The renderer then replays
    direct-source static-discovery binding and exact canonical MusicBrainz
    artist ID equality for every displayed row.
    """
    root, directory = _preview_directory(local_root=local_root, output_directory=output_directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".artist-detail-preview-", dir=root))
    try:
        payload_path = temporary / "musicbrainz-credit-metadata.json"
        payload, payload_sha256 = export_local_musicbrainz_credit_artist_detail_payload(
            credit_metadata=credit_metadata,
            static_discovery=static_discovery,
            static_artist_id=static_artist_id,
            local_root=local_root,
            output=payload_path,
        )
        _verify_approval(approval=approval, credit_metadata=credit_metadata, payload=payload)
        html_path = temporary / "index.html"
        html_path.write_text(_html(payload), encoding="utf-8", newline="\n")
        temporary.replace(directory)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return LocalMusicBrainzCreditArtistDetailHtmlPreview(
        payload=payload,
        payload_sha256=payload_sha256,
        directory=directory,
        html_path=directory / "index.html",
        payload_path=directory / "musicbrainz-credit-metadata.json",
    )


def _preview_directory(*, local_root: Path, output_directory: Path) -> tuple[Path, Path]:
    """Validate one fresh destination beneath the explicit local cache root."""
    try:
        root = local_root.resolve(strict=True)
    except OSError as error:
        raise LocalMusicBrainzCreditArtistDetailError("local root must already exist") from error
    if root.name != ".cache" or not root.is_dir():
        raise LocalMusicBrainzCreditArtistDetailError(
            "local root must be an existing .cache directory"
        )
    if root.is_relative_to(_REPOSITORY_DIST.resolve(strict=False)):
        raise LocalMusicBrainzCreditArtistDetailError(
            "local root must not be inside this repository's dist"
        )
    if output_directory.exists() or output_directory.is_symlink():
        raise LocalMusicBrainzCreditArtistDetailError("local HTML preview directory already exists")
    directory = output_directory.resolve(strict=False)
    if not directory.is_relative_to(root):
        raise LocalMusicBrainzCreditArtistDetailError(
            "local HTML preview directory must stay below local .cache"
        )
    return root, directory


def _html(payload: LocalMusicBrainzCreditArtistDetailPayload) -> str:
    """Return a deterministic, static HTML view with escaped source text."""
    rows = "".join(_row_html(row) for row in payload.rows)
    artist_url = f"https://musicbrainz.org/artist/{payload.musicbrainz_artist_id}"
    return _template("musicbrainz-credit-artist-detail-local.html").substitute(
        publication_status=escape(payload.publication_status, quote=True),
        static_artist_id=escape(payload.static_artist_id),
        artist_url=escape(artist_url, quote=True),
        musicbrainz_artist_id=escape(payload.musicbrainz_artist_id),
        rows=rows,
    )


def _verify_approval(
    *, approval: Path, credit_metadata: Path, payload: LocalMusicBrainzCreditArtistDetailPayload
) -> None:
    """Require the already-issued policy decision without creating one here."""
    try:
        decision = CreditMetadataPublicationApproval.model_validate_json(approval.read_bytes())
        metadata = MusicBrainzCreditStaticMetadataPayload.model_validate_json(
            credit_metadata.read_bytes()
        )
    except (OSError, ValueError) as error:
        raise LocalMusicBrainzCreditArtistDetailError(
            "local HTML preview requires a valid explicit credit metadata approval"
        ) from error
    if (
        decision.candidate_database_sha256,
        decision.public_database_sha256,
        decision.static_discovery_sha256,
    ) != (
        metadata.candidate_database_sha256,
        payload.public_database_sha256,
        payload.static_discovery_sha256,
    ):
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata approval does not bind local preview inputs"
        )
    if any(row.credit_artifact_sha256 != decision.credit_artifact_sha256 for row in payload.rows):
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata approval does not bind every displayed source row"
        )


def _row_html(row: MusicBrainzCreditMetadataRow) -> str:
    """Render one typed metadata row without granting it discovery semantics."""
    members = "".join(
        _template("musicbrainz-credit-artist-detail-local-member.html")
        .substitute(
            position=member.position,
            credited_name=escape(member.credited_name),
            join_phrase=escape(member.join_phrase),
        )
        .rstrip("\n")
        for member in row.credit_members
    )
    return _template("musicbrainz-credit-artist-detail-local-row.html").substitute(
        entity_kind_value=escape(row.entity_kind, quote=True),
        musicbrainz_entity_id=escape(row.musicbrainz_entity_id, quote=True),
        entity_kind=escape(row.entity_kind.capitalize()),
        title=escape(row.title),
        members=members,
    )


def _template(name: str) -> Template:
    """Load one checked-in local-preview template, never a release asset."""
    try:
        return Template((_STATIC_ROOT / name).read_text(encoding="utf-8"))
    except OSError as error:
        raise LocalMusicBrainzCreditArtistDetailError(
            "local HTML preview template is unavailable"
        ) from error
