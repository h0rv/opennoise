"""Exact-ID, local-only joins of portable MusicBrainz observations and names.

Source observations and canonical names stay immutable. Display normalization
does not resolve identities. This catalog has no public promotion path.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyReceipt,
    iter_verified_direct_canonical_artist_names,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic runtime annotation.

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_QUERY_ARTISTS: Final = 100
MAX_QUERY_OBSERVATIONS: Final = 1000
MAX_LABEL_CHARACTERS: Final = 4096
MAX_DATABASE_BYTES: Final = 512 * 1024 * 1024
_SAMPLE_LIMIT: Final = 20
_BIDI_CONTROLS: Final = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)
_REVISION: Final = "local-musicbrainz-candidate-catalog-v1"
_LOCAL_CACHE: Final = Path(__file__).resolve().parents[3] / ".cache"


class CandidateCatalogError(ValueError):
    """Report a broken custody join, generated artifact, or query boundary."""


class CandidateCatalogReceipt(FrozenModel):
    """Hash-bound local artifact, preserving the source's custody-only policy."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    revision: Literal["local-musicbrainz-candidate-catalog-v1"] = _REVISION
    scope: Literal["local_research_only"] = "local_research_only"
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_promotion_authorized: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    release_memberships_or_tags_used: Literal[False] = False
    canonical_name_source: Literal["musicbrainz_release_group_nested_artist_name_only"] = (
        "musicbrainz_release_group_nested_artist_name_only"
    )
    display_normalization: Literal["NFC_whitespace_control_and_bidi_cleanup_v1"] = (
        "NFC_whitespace_control_and_bidi_cleanup_v1"
    )
    builder_sha256: Sha256
    direct_receipt_byte_sha256: Sha256
    direct_receipt_output_sha256: Sha256
    direct_object_sha256: Sha256
    name_receipt_byte_sha256: Sha256
    name_receipt_output_sha256: Sha256
    name_object_sha256: Sha256
    database_sha256: Sha256
    database_bytes: int = Field(gt=0, le=MAX_DATABASE_BYTES)
    logical_sha256: Sha256
    quality_sha256: Sha256
    observation_count: int = Field(ge=0, le=1_000_000)
    distinct_seed_artist_count: int = Field(ge=0)
    seed_count: int = Field(ge=0)
    artist_count: int = Field(ge=0, le=250_000)
    named_artist_count: int = Field(ge=0)
    unresolved_artist_count: int = Field(ge=0)
    output_sha256: Sha256

    @model_validator(mode="after")
    def coverage_partitions_artists(self) -> CandidateCatalogReceipt:
        """Require exact-ID name coverage to partition the direct cohort."""
        if self.named_artist_count + self.unresolved_artist_count != self.artist_count:
            raise ValueError("candidate name coverage does not partition artists")
        if self.distinct_seed_artist_count > self.observation_count:
            raise ValueError("candidate pairs exceed source observations")
        return self


def normalize_display_name(canonical_name: str) -> str | None:
    """Normalize presentation while preserving case, accents, punctuation and joiners.

    Control and bidi formatting characters are removed. Unicode whitespace is
    collapsed. The original label remains a separate, unchanged canonical fact.
    An unusable display label abstains; the MBID never changes.
    """
    if len(canonical_name) > MAX_LABEL_CHARACTERS:
        raise CandidateCatalogError("canonical label exceeds character bound")
    normalized = unicodedata.normalize("NFC", canonical_name)
    cleaned = "".join(
        " " if char.isspace() else char
        for char in normalized
        if char.isspace()
        or (unicodedata.category(char) not in {"Cc", "Cs"} and char not in _BIDI_CONTROLS)
    )
    return " ".join(cleaned.split()) or None


def require_local_candidate_destination(directory: Path) -> None:
    """Reject public destinations and symlink escapes for local research writes."""
    if directory.is_symlink() or not directory.resolve().is_relative_to(_LOCAL_CACHE.resolve()):
        raise CandidateCatalogError("local candidate output must stay inside project .cache")
    if _LOCAL_CACHE.is_symlink():
        raise CandidateCatalogError("project .cache must not be a symlink")


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise CandidateCatalogError("candidate count is unavailable")
    return int(row[0])


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE artist (
          artist_mbid TEXT PRIMARY KEY,
          canonical_name TEXT,
          display_name TEXT,
          name_status TEXT NOT NULL CHECK(name_status IN ('exact','unresolved','unusable_display'))
        ) WITHOUT ROWID;
        CREATE TABLE direct_claim (
          seed_id TEXT NOT NULL,
          artist_mbid TEXT NOT NULL REFERENCES artist(artist_mbid),
          musicbrainz_genre_id TEXT NOT NULL,
          source_record_id TEXT NOT NULL,
          source_record_sha256 TEXT NOT NULL,
          source_evidence_ref TEXT NOT NULL,
          PRIMARY KEY (seed_id,artist_mbid,musicbrainz_genre_id,source_record_sha256,
                       source_evidence_ref)
        ) WITHOUT ROWID;
        CREATE TABLE seed_artist (
          seed_id TEXT NOT NULL,
          artist_mbid TEXT NOT NULL REFERENCES artist(artist_mbid),
          PRIMARY KEY(seed_id,artist_mbid)
        ) WITHOUT ROWID;
        CREATE INDEX seed_artist_by_artist ON seed_artist(artist_mbid,seed_id);
        CREATE INDEX artist_by_display ON artist(display_name,artist_mbid);
        """
    )


def _populate(
    connection: sqlite3.Connection,
    direct: DirectProperGenreCustodyReceipt,
    direct_store: Path,
    names: DirectCanonicalArtistNameCustodyReceipt,
    name_store: Path,
) -> None:
    _schema(connection)
    with connection:
        for claim in iter_verified_portable_direct_proper_genre_claims(
            direct, object_store=direct_store
        ):
            connection.execute(
                "INSERT OR IGNORE INTO artist VALUES (?,NULL,NULL,'unresolved')",
                (claim.artist_mbid,),
            )
            connection.execute(
                "INSERT INTO direct_claim VALUES (?,?,?,?,?,?)",
                (
                    claim.seed_id,
                    claim.artist_mbid,
                    claim.musicbrainz_genre_id,
                    claim.source_record_id,
                    claim.source_record_sha256,
                    claim.source_evidence_ref,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO seed_artist VALUES (?,?)",
                (claim.seed_id, claim.artist_mbid),
            )
        for name in iter_verified_direct_canonical_artist_names(names, object_store=name_store):
            display = normalize_display_name(name.canonical_name)
            changed = connection.execute(
                "UPDATE artist SET canonical_name=?,display_name=?,name_status=? "
                "WHERE artist_mbid=?",
                (
                    name.canonical_name,
                    display,
                    "exact" if display is not None else "unusable_display",
                    name.artist_mbid,
                ),
            ).rowcount
            if changed != 1:
                raise CandidateCatalogError("name custody contains an artist outside direct cohort")
        if _scalar(connection, "SELECT COUNT(*) FROM artist") != direct.artist_mbid_count:
            raise CandidateCatalogError("exact artist cohort does not replay")
        if _scalar(connection, "SELECT COUNT(*) FROM direct_claim") != direct.claim_count:
            raise CandidateCatalogError("source observations do not replay")
        if _scalar(connection, "SELECT COUNT(*) FROM artist WHERE canonical_name IS NOT NULL") != (
            names.canonical_name_count
        ):
            raise CandidateCatalogError("name facts do not replay")


def _logical_rows(connection: sqlite3.Connection) -> Iterator[object]:
    for table, order in (
        ("metadata", "key"),
        ("artist", "artist_mbid"),
        (
            "direct_claim",
            "seed_id,artist_mbid,musicbrainz_genre_id,source_record_sha256,source_evidence_ref",
        ),
        ("seed_artist", "seed_id,artist_mbid"),
    ):
        # Identifiers are fixed internal literals, never caller SQL.
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):  # noqa: S608
            yield [table, list(row)]


def _logical_sha256(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in _logical_rows(connection):
        digest.update(canonical_json(row) + b"\n")
    return digest.hexdigest()


def _quality(connection: sqlite3.Connection) -> dict[str, object]:
    """Report ambiguity without merging homonyms or propagating memberships."""
    counts = {
        "observation_count": _scalar(connection, "SELECT COUNT(*) FROM direct_claim"),
        "distinct_seed_artist_count": _scalar(connection, "SELECT COUNT(*) FROM seed_artist"),
        "seed_count": _scalar(connection, "SELECT COUNT(DISTINCT seed_id) FROM seed_artist"),
        "artist_count": _scalar(connection, "SELECT COUNT(*) FROM artist"),
        "named_artist_count": _scalar(
            connection, "SELECT COUNT(*) FROM artist WHERE canonical_name IS NOT NULL"
        ),
        "unresolved_artist_count": _scalar(
            connection, "SELECT COUNT(*) FROM artist WHERE canonical_name IS NULL"
        ),
        "display_label_changed_count": _scalar(
            connection,
            "SELECT COUNT(*) FROM artist WHERE canonical_name IS NOT NULL "
            "AND (display_name IS NULL OR canonical_name != display_name)",
        ),
        "unusable_display_count": _scalar(
            connection, "SELECT COUNT(*) FROM artist WHERE name_status='unusable_display'"
        ),
        "named_seed_artist_count": _scalar(
            connection,
            "SELECT COUNT(*) FROM seed_artist JOIN artist USING(artist_mbid) "
            "WHERE canonical_name IS NOT NULL",
        ),
        "source_record_conflict_artist_count": _scalar(
            connection,
            "SELECT COUNT(*) FROM (SELECT artist_mbid FROM direct_claim GROUP BY artist_mbid "
            "HAVING COUNT(DISTINCT source_record_sha256)>1)",
        ),
        "multi_genre_identity_seed_count": _scalar(
            connection,
            "SELECT COUNT(*) FROM (SELECT seed_id FROM direct_claim GROUP BY seed_id "
            "HAVING COUNT(DISTINCT musicbrainz_genre_id)>1)",
        ),
        "display_collision_label_count": _scalar(
            connection,
            "SELECT COUNT(*) FROM (SELECT display_name FROM artist WHERE display_name IS NOT NULL "
            "GROUP BY display_name HAVING COUNT(*)>1)",
        ),
    }
    counts["additional_observations_per_pair_count"] = (
        counts["observation_count"] - counts["distinct_seed_artist_count"]
    )
    per_seed = [
        {
            "seed_id": str(seed),
            "artist_count": int(total),
            "named_artist_count": int(named),
            "displayable_artist_count": int(displayable),
            "unresolved_artist_count": int(total) - int(named),
        }
        for seed, total, named, displayable in connection.execute(
            "SELECT seed_id,COUNT(*),COUNT(canonical_name),COUNT(display_name) "
            "FROM seed_artist JOIN artist USING(artist_mbid) GROUP BY seed_id ORDER BY seed_id"
        )
    ]
    collisions = [
        {"display_name": str(label), "distinct_artist_count": int(count)}
        for label, count in connection.execute(
            "SELECT display_name,COUNT(*) FROM artist WHERE display_name IS NOT NULL "
            "GROUP BY display_name HAVING COUNT(*)>1 ORDER BY COUNT(*) DESC,display_name LIMIT ?",
            (_SAMPLE_LIMIT,),
        )
    ]
    unresolved = [
        str(row[0])
        for row in connection.execute(
            "SELECT artist_mbid FROM artist WHERE canonical_name IS NULL "
            "ORDER BY artist_mbid LIMIT ?",
            (_SAMPLE_LIMIT,),
        )
    ]
    return {
        "revision": "local-musicbrainz-candidate-quality-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "source_facets": ["artist_direct_proper_genre"],
        "identity_join": "exact_artist_mbid_only",
        "unresolved_names_are_not_negative_memberships": True,
        "same_label_artists_remain_distinct": True,
        "counts": counts,
        "per_seed": per_seed,
        "display_collision_sample": collisions,
        "unresolved_artist_sample": unresolved,
        "sample_limit": _SAMPLE_LIMIT,
    }


def build_local_musicbrainz_candidate_catalog(
    *,
    direct_receipt_path: Path,
    direct_object_store: Path,
    name_receipt_path: Path,
    name_object_store: Path,
    output_directory: Path,
) -> CandidateCatalogReceipt:
    """Verify both portable sources, join exact IDs, then atomically seal local files."""
    require_local_candidate_destination(output_directory)
    if output_directory.exists():
        raise FileExistsError(f"refusing to replace local candidate: {output_directory}")
    direct_bytes = direct_receipt_path.read_bytes()
    name_bytes = name_receipt_path.read_bytes()
    direct = DirectProperGenreCustodyReceipt.model_validate_json(direct_bytes)
    names = DirectCanonicalArtistNameCustodyReceipt.model_validate_json(name_bytes)
    direct_sha256 = hashlib.sha256(direct_bytes).hexdigest()
    if (
        names.direct_custody_receipt_byte_sha256,
        names.direct_custody_receipt_output_sha256,
        names.direct_claims_object_sha256,
        names.direct_artist_mbid_count,
    ) != (
        direct_sha256,
        direct.output_sha256,
        direct.claims_object_sha256,
        direct.artist_mbid_count,
    ):
        raise CandidateCatalogError("name receipt is bound to a different direct cohort")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".musicbrainz-candidate-", dir=output_directory.parent
    ) as tmp:
        staged = Path(tmp) / "candidate"
        staged.mkdir()
        database = staged / "catalog.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            _populate(connection, direct, direct_object_store, names, name_object_store)
            with connection:
                connection.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    (
                        ("revision", _REVISION),
                        ("direct_receipt_output_sha256", direct.output_sha256),
                        ("name_receipt_output_sha256", names.output_sha256),
                        ("scope", "local_research_only"),
                    ),
                )
            quality = _quality(connection)
            logical_sha = _logical_sha256(connection)
        quality_bytes = canonical_json(quality) + b"\n"
        (staged / "quality.json").write_bytes(quality_bytes)
        counts = quality["counts"]
        if not isinstance(counts, dict):
            raise CandidateCatalogError("quality report lacks counts")
        database_sha, database_bytes = sha256_file(database)
        receipt = CandidateCatalogReceipt(
            builder_sha256=sha256_file(Path(__file__))[0],
            direct_receipt_byte_sha256=direct_sha256,
            direct_receipt_output_sha256=direct.output_sha256,
            direct_object_sha256=direct.claims_object_sha256,
            name_receipt_byte_sha256=hashlib.sha256(name_bytes).hexdigest(),
            name_receipt_output_sha256=names.output_sha256,
            name_object_sha256=names.names_object_sha256,
            database_sha256=database_sha,
            database_bytes=database_bytes,
            logical_sha256=logical_sha,
            quality_sha256=hashlib.sha256(quality_bytes).hexdigest(),
            observation_count=int(counts["observation_count"]),
            distinct_seed_artist_count=int(counts["distinct_seed_artist_count"]),
            seed_count=int(counts["seed_count"]),
            artist_count=int(counts["artist_count"]),
            named_artist_count=int(counts["named_artist_count"]),
            unresolved_artist_count=int(counts["unresolved_artist_count"]),
            output_sha256="0" * 64,
        )
        receipt = receipt.model_copy(
            update={
                "output_sha256": sha256_json(
                    receipt.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )
        (staged / "receipt.json").write_bytes(
            canonical_json(receipt.model_dump(mode="json")) + b"\n"
        )
        verify_local_musicbrainz_candidate_catalog(directory=staged)
        if output_directory.exists():
            raise FileExistsError(f"refusing to replace local candidate: {output_directory}")
        staged.rename(output_directory)
    return receipt


def verify_local_musicbrainz_candidate_catalog(*, directory: Path) -> CandidateCatalogReceipt:
    """Verify generated byte and logical bindings before a local query or model read."""
    receipt = CandidateCatalogReceipt.model_validate_json((directory / "receipt.json").read_bytes())
    if receipt.output_sha256 != sha256_json(
        receipt.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise CandidateCatalogError("candidate receipt self-hash does not replay")
    database = directory / "catalog.sqlite"
    if database.is_symlink() or sha256_file(database) != (
        receipt.database_sha256,
        receipt.database_bytes,
    ):
        raise CandidateCatalogError("candidate database bytes do not match receipt")
    if sha256_file(directory / "quality.json")[0] != receipt.quality_sha256:
        raise CandidateCatalogError("candidate quality bytes do not match receipt")
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise CandidateCatalogError("candidate database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CandidateCatalogError("candidate database has invalid foreign keys")
        if _logical_sha256(connection) != receipt.logical_sha256:
            raise CandidateCatalogError("candidate logical content does not match receipt")
    return receipt


def query_local_musicbrainz_candidate_genre(
    *, directory: Path, seed_id: str, limit: int = 20
) -> dict[str, object]:
    """Return a bounded honest preview with exact IDs, missing names and source receipts."""
    if not seed_id or not 1 <= limit <= MAX_QUERY_ARTISTS:
        raise CandidateCatalogError("query requires an exact seed ID and limit from 1 to 100")
    receipt = verify_local_musicbrainz_candidate_catalog(directory=directory)
    database = directory / "catalog.sqlite"
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        count_row = connection.execute(
            "SELECT COUNT(*),COUNT(canonical_name) FROM seed_artist JOIN artist USING(artist_mbid) "
            "WHERE seed_id=?",
            (seed_id,),
        ).fetchone()
        if count_row is None:
            raise CandidateCatalogError("query count is unavailable")
        total, named = int(count_row[0]), int(count_row[1])
        artists: list[dict[str, object]] = []
        for mbid, canonical, display, status in connection.execute(
            "SELECT artist_mbid,canonical_name,display_name,name_status "
            "FROM seed_artist JOIN artist USING(artist_mbid) WHERE seed_id=? "
            "ORDER BY artist_mbid LIMIT ?",
            (seed_id, limit),
        ):
            observations = [
                {
                    "musicbrainz_genre_id": str(genre),
                    "source_record_id": str(record),
                    "source_record_sha256": str(sha),
                    "source_evidence_ref": str(evidence),
                    "facet": "artist_direct_proper_genre",
                }
                for genre, record, sha, evidence in connection.execute(
                    "SELECT musicbrainz_genre_id,source_record_id,source_record_sha256,"
                    "source_evidence_ref FROM direct_claim WHERE seed_id=? AND artist_mbid=? "
                    "ORDER BY musicbrainz_genre_id,source_record_sha256,source_evidence_ref "
                    "LIMIT ?",
                    (seed_id, mbid, MAX_QUERY_OBSERVATIONS + 1),
                )
            ]
            if len(observations) > MAX_QUERY_OBSERVATIONS:
                raise CandidateCatalogError("query observation bound exceeded")
            artists.append(
                {
                    "artist_mbid": str(mbid),
                    "canonical_name": canonical,
                    "display_name": display,
                    "name_status": str(status),
                    "musicbrainz_url": f"https://musicbrainz.org/artist/{mbid}",
                    "observations": observations,
                }
            )
    return {
        "revision": "local-musicbrainz-candidate-genre-preview-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "membership_promotion_authorized": False,
        "seed_id": seed_id,
        "state": "observed" if total else "no_direct_observations",
        "artist_count": total,
        "named_artist_count": named,
        "unresolved_artist_count": total - named,
        "returned_artist_count": len(artists),
        "truncated": len(artists) < total,
        "order": "exact_artist_mbid_ascending_not_relevance",
        "catalog_output_sha256": receipt.output_sha256,
        "direct_object_sha256": receipt.direct_object_sha256,
        "name_object_sha256": receipt.name_object_sha256,
        "artists": artists,
    }
