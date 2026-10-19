"""Import complete retained CC0 cultural cohorts into the ordinary native catalog.

Source claim observations and canonical direct facts have different denominators.
The fixed capture order is lexical source key; repeated captures are not votes.
"""

# ruff: noqa: SLF001 -- reuse verified source replay and native credit materialization.
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opennoise.catalog.artist_identity import resolve_artist
from opennoise.catalog.entities import EntityProjector
from opennoise.common import canonical_json
from opennoise.db import Database
from opennoise.deployment.musicbrainz_credit_portable_release import PortableMusicBrainzCreditSource
from opennoise.ingest.musicbrainz import artist_credit_catalog_candidate as native_credits
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditRefreshCandidateArtifact,
)
from opennoise.ingest.musicbrainz.release_hydration import (
    CachedResponse,
    MusicBrainzReleaseHydrationArtifact,
    materialize_hydration_catalog,
)
from opennoise.models.catalog import (
    EntityProjection,
    ExternalIdentity,
    IdentifierClaim,
    NameClaim,
    RelationClaim,
)
from opennoise.pipeline.artist_identity_replay import CORE_SHA, _normalized_graph, digest
from opennoise.pipeline.portable_foundation import _verified_cultural
from opennoise.serving.public.artist_membership_adapter import (
    CertifiedPublicDirectSelector,
    CertifiedPublicMembershipAdapterPolicy,
    adapt_certified_public_membership_input,
    source_policy_for_adapter,
    verify_certified_public_membership_receipt,
)
from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStore

PACKS = (
    (
        "wikidata_cultural_context",
        "3c931909700e2840dff10e2afd2463e9123faa2a7b36e5fc1b90c472677453a7",
    ),
    (
        "wikidata_independent_cultural_context",
        "df9763aef5b3f5801cc9ef999ecd34b24b97c588dc25679a2adaf8432461cfa5",
    ),
)
MAX_BYTES = 32_000_000
SOURCE_MAX_BYTES = 2_000_000
MAX_INPUT_FILES = 32
PAGE_SIZE = 50
EXPECTED_ARTISTS = 433
EXPECTED_NAMELESS = 3
EXPECTED_SUPPORTED_NEIGHBORS = 72
EXPECTED_DIRECTED_EDGES = 580
EXPECTED_NOMINATIONS = 150


@dataclass(frozen=True)
class CulturalPack:
    """One exact raw-verified input, never a benchmark neighbor or inferred target."""

    directory: Path
    source_key: str
    receipt_sha256: str
    manifest: dict[str, Any]
    artists: list[dict[str, Any]]


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_pack(directory: Path, source_key: str, pin: str) -> CulturalPack:
    """Close the complete inventory before using the existing native raw verifier."""
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("Cultural source paths cannot traverse symlinks")
    files = list(directory.rglob("*"))
    if len(files) > MAX_INPUT_FILES:
        raise ValueError("Cultural source file count exceeded")
    if any(p.is_symlink() for p in files):
        raise ValueError("Cultural source paths cannot traverse symlinks")
    if sum(p.stat().st_size for p in files if p.is_file()) > SOURCE_MAX_BYTES:
        raise ValueError("Cultural source byte bound exceeded")
    expected = dict(PACKS).get(source_key)
    if expected != pin or digest(directory / "receipt.json") != pin:
        raise ValueError("Cultural source receipt differs from the fixed source plan")
    receipt = json.loads((directory / "receipt.json").read_bytes())
    actual = {
        str(p.relative_to(directory))
        for p in files
        if p.is_file() and p != directory / "receipt.json"
    }
    if actual != set(receipt["sha256"]):
        raise ValueError("Cultural source inventory differs, including nested receipts")
    manifest, artists = _verified_cultural(directory)
    return CulturalPack(directory, source_key, pin, manifest, artists)


def _registered_source(
    connection: sqlite3.Connection, pack: CulturalPack, source: int, policy: int
) -> None:
    expected = (
        pack.source_key,
        "Retained CC0 cultural source " + pack.source_key,
        "https://query.wikidata.org/sparql",
        "CC0-1.0",
        "https://www.wikidata.org/wiki/Wikidata:Licensing",
        "user_supplied_local",
        f"cc0-cultural-catalog:{pack.source_key}",
        1,
        "public_domain",
        0,
        None,
    )
    row = connection.execute(
        """SELECT s.source_key,s.name,s.homepage_url,s.license_name,s.license_url,
                  s.acquisition_kind,
                  r.policy_key,r.policy_version,r.classification,r.local_only,r.expires_at
           FROM data_sources s JOIN rights_policies r ON r.id=s.default_policy_id
           WHERE s.id=? AND r.id=?
             AND EXISTS(SELECT 1 FROM rights_policy_seals WHERE policy_id=r.id)""",
        (source, policy),
    ).fetchone()
    permissions = {
        tuple(r)
        for r in connection.execute(
            "SELECT use_kind,decision FROM active_rights_policy_permissions WHERE policy_id=?",
            (policy,),
        )
    }
    if (
        row is None
        or tuple(row) != expected
        or permissions
        != {
            (use, "allow")
            for use in ("normalize", "local_search", "display", "embed", "train", "export")
        }
    ):
        raise ValueError("Existing cultural source has incompatible license or policy")
    snapshots = connection.execute(
        """SELECT id,snapshot_ref,snapshot_kind,manifest_sha256,acquired_at,policy_id
           FROM source_snapshots WHERE source_id=?""",
        (source,),
    ).fetchall()
    expected_snapshot = (
        f"retained:{pack.source_key}:{pack.manifest['acquired_utc']}",
        "full",
        digest(pack.directory / "manifest.json"),
        pack.manifest["acquired_utc"],
        policy,
    )
    if len(snapshots) != 1 or tuple(snapshots[0])[1:] != expected_snapshot:
        raise ValueError("Existing cultural source snapshot custody differs")
    artifacts = connection.execute(
        """SELECT artifact_ref,logical_name,media_type,byte_size,sha256,vault_key,policy_id
           FROM source_artifacts WHERE snapshot_id=? ORDER BY artifact_ref""",
        (snapshots[0][0],),
    ).fetchall()
    expected_artifacts = sorted(
        (
            b["raw_path"],
            "Retained raw SPARQL response",
            "application/json",
            b["response_bytes"],
            b["response_sha256"],
            b["response_sha256"],
            policy,
        )
        for b in pack.manifest["batches"]
    )
    if [tuple(r) for r in artifacts] != expected_artifacts:
        raise ValueError("Existing cultural source artifact custody differs")
    suppressed = connection.execute(
        """SELECT 1 FROM active_suppressions x WHERE x.use_kind IN ('all','normalize')
           AND ((x.target_kind='source' AND x.target_ref=?)
             OR (x.target_kind='snapshot' AND x.target_ref=?)
             OR (x.target_kind='artifact' AND x.target_ref IN (
                 SELECT CAST(id AS TEXT) FROM source_artifacts WHERE snapshot_id=?))) LIMIT 1""",
        (str(source), str(snapshots[0][0]), snapshots[0][0]),
    ).fetchone()
    if suppressed is not None:
        raise ValueError("Cultural source is suppressed for normalization")


def _source(connection: sqlite3.Connection, pack: CulturalPack) -> tuple[int, int]:
    key = pack.source_key
    existing = connection.execute(
        "SELECT id,default_policy_id FROM data_sources WHERE source_key=?", (key,)
    ).fetchone()
    if existing is not None:
        _registered_source(connection, pack, int(existing[0]), int(existing[1]))
        return int(existing[0]), int(existing[1])
    now = datetime.now(UTC).isoformat()
    policy = connection.execute(
        """INSERT INTO rights_policies(
               policy_key,policy_version,classification,local_only,basis,reviewed_at)
           VALUES(?,1,'public_domain',0,
                  'Wikidata CC0; verified retained native SPARQL captures',?)""",
        (f"cc0-cultural-catalog:{key}", now),
    ).lastrowid
    if policy is None:
        raise RuntimeError("Source policy registration failed")
    for use in ("normalize", "local_search", "display", "embed", "train", "export"):
        connection.execute(
            """INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason)
               VALUES(?,?,'allow','Wikidata structured data CC0')""",
            (policy, use),
        )
    connection.execute(
        "INSERT INTO rights_policy_seals(policy_id,sealed_at) VALUES(?,?)", (policy, now)
    )
    source = connection.execute(
        """INSERT INTO data_sources(source_key,name,homepage_url,license_name,license_url,
               acquisition_kind,default_policy_id) VALUES(?,?,'https://query.wikidata.org/sparql',
               'CC0-1.0','https://www.wikidata.org/wiki/Wikidata:Licensing','user_supplied_local',?)""",
        (key, "Retained CC0 cultural source " + key, policy),
    ).lastrowid
    if source is None:
        raise RuntimeError("Source registration failed")
    snapshot_ref = f"retained:{key}:{pack.manifest['acquired_utc']}"
    snapshot = connection.execute(
        """INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,manifest_sha256,
               acquired_at,policy_id) VALUES(?,?,'full',?,?,?)""",
        (
            source,
            snapshot_ref,
            digest(pack.directory / "manifest.json"),
            pack.manifest["acquired_utc"],
            policy,
        ),
    ).lastrowid
    for batch in pack.manifest["batches"]:
        connection.execute(
            """INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,
                   byte_size,sha256,vault_key,policy_id) VALUES(?,?,'Retained raw SPARQL response',
                   'application/json',?,?,?,?)""",
            (
                snapshot,
                batch["raw_path"],
                batch["response_bytes"],
                batch["response_sha256"],
                batch["response_sha256"],
                policy,
            ),
        )
    _registered_source(connection, pack, source, policy)
    return source, policy


def _normalization_entities(connection: sqlite3.Connection, projection: EntityProjection) -> None:
    """Gate exact existing subjects and relation targets before any new observation."""
    entities: set[int] = set()
    if projection.entity_kind == "artist":
        found = resolve_artist(
            connection, projection.identifiers, subject_qid=projection.source_identity.value
        )
        if found is not None:
            entities.add(found)
    identities = [projection.source_identity]
    identities.extend(
        claim.target for claim in projection.claims if isinstance(claim, RelationClaim)
    )
    for identity in identities:
        entities.update(
            int(row[0])
            for row in connection.execute(
                "SELECT DISTINCT entity_id FROM entity_identifiers "
                "WHERE namespace=? AND normalized_value=?",
                (identity.namespace, identity.value),
            )
        )
    for entity in entities:
        if (
            connection.execute(
                "SELECT 1 FROM active_suppressions WHERE target_kind='entity' AND target_ref=? "
                "AND use_kind IN ('all','normalize')",
                (str(entity),),
            ).fetchone()
            is not None
        ):
            raise ValueError("Exact projection entity is suppressed for normalization")


def _persist_projection(
    connection: sqlite3.Connection,
    pack: CulturalPack,
    batch: dict[str, Any],
    projection: EntityProjection,
) -> None:
    _normalization_entities(connection, projection)
    source, policy = _source(connection, pack)
    fingerprint = _hash(
        {
            "projection": projection.model_dump(mode="json"),
            "raw_response_sha256": batch["response_sha256"],
        }
    )
    snapshot = f"retained:{pack.source_key}:{pack.manifest['acquired_utc']}"
    rows = connection.execute(
        """SELECT id,policy_id,observed_at,ingest_attempt_ref FROM provenance_records
           WHERE source_id=? AND snapshot_ref=?
           AND artifact_sha256=? AND record_fingerprint=?
           AND parser_release_ref='verified-cultural-catalog-v1'""",
        (source, snapshot, batch["response_sha256"], fingerprint),
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("Ambiguous projection provenance")
    if rows:
        if tuple(rows[0])[1:] != (
            policy,
            pack.manifest["acquired_utc"],
            "offline-cc0-cultural-catalog",
        ):
            raise ValueError("Existing projection provenance custody differs")
        prov = int(rows[0][0])
    else:
        prov = connection.execute(
            """INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,artifact_sha256,
                   record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at)
                   VALUES(?,?,?,?,?,'verified-cultural-catalog-v1','offline-cc0-cultural-catalog',?)""",
            (
                source,
                policy,
                snapshot,
                batch["response_sha256"],
                fingerprint,
                pack.manifest["acquired_utc"],
            ),
        ).lastrowid
    if prov is None:
        raise RuntimeError("Projection provenance missing")
    if (
        connection.execute(
            "SELECT 1 FROM active_suppressions WHERE target_kind='provenance' AND target_ref=? "
            "AND use_kind IN ('all','normalize')",
            (str(prov),),
        ).fetchone()
        is not None
    ):
        raise ValueError("Projection provenance is suppressed for normalization")
    EntityProjector().persist(connection, projection, provenance_id=prov, policy_id=policy)


def ingest_pack(connection: sqlite3.Connection, pack: CulturalPack) -> None:
    """Atomically project a pack without committing the caller's transaction."""
    if not connection.in_transaction:
        connection.execute("BEGIN")
    connection.execute("SAVEPOINT cultural_pack_projection")
    try:
        _ingest_pack(connection, pack)
    except BaseException:
        connection.execute("ROLLBACK TO cultural_pack_projection")
        connection.execute("RELEASE cultural_pack_projection")
        raise
    connection.execute("RELEASE cultural_pack_projection")


def _ingest_pack(connection: sqlite3.Connection, pack: CulturalPack) -> None:
    """Project exact identities/P136 and raw English labels with independent custody."""
    # Preflight the whole pack before creating provenance or mutating earlier subjects.
    for row in pack.artists:
        _normalization_entities(
            connection,
            EntityProjection(
                entity_kind="artist",
                source_identity=ExternalIdentity(
                    namespace="wikidata", value=row["wikidata_artist_id"]
                ),
                names=(),
                identifiers=(
                    IdentifierClaim(
                        type_key="musicbrainz_artist_id",
                        namespace="musicbrainz",
                        value=row["musicbrainz_artist_id"],
                    ),
                ),
                claims=tuple(
                    RelationClaim(
                        property_key="genre",
                        target=ExternalIdentity(namespace="wikidata", value=claim["value_qid"]),
                        target_kind="genre",
                        rank=None,
                    )
                    for claim in row["claims"]
                    if claim["property_id"] == "P136"
                ),
            ),
        )
    for row in sorted(pack.artists, key=lambda item: item["musicbrainz_artist_id"]):
        batch = next(
            b
            for b in pack.manifest["batches"]
            if row["musicbrainz_artist_id"] in b["requested_mbids"]
        )
        names = (
            (NameClaim(kind="primary", value=row["label"], language_tag="en"),)
            if row["label"]
            else ()
        )
        projection = EntityProjection(
            entity_kind="artist",
            source_identity=ExternalIdentity(namespace="wikidata", value=row["wikidata_artist_id"]),
            names=names,
            identifiers=(
                IdentifierClaim(
                    type_key="musicbrainz_artist_id",
                    namespace="musicbrainz",
                    value=row["musicbrainz_artist_id"],
                ),
            ),
            claims=tuple(
                RelationClaim(
                    property_key="genre",
                    target=ExternalIdentity(namespace="wikidata", value=claim["value_qid"]),
                    target_kind="genre",
                    rank=None,
                )
                for claim in sorted(row["claims"], key=lambda c: (c["property_id"], c["value_qid"]))
                if claim["property_id"] == "P136"
            ),
        )
        _persist_projection(connection, pack, batch, projection)
    # The English labels are observations on exact target QIDs, never label joins.
    accepted = {
        (r["musicbrainz_artist_id"], r["wikidata_artist_id"], c["value_qid"])
        for r in pack.artists
        for c in r["claims"]
        if c["property_id"] == "P136"
    }
    for batch in pack.manifest["batches"]:
        raw = (pack.directory / batch["raw_path"]).read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != batch["response_sha256"]
            or len(raw) != batch["response_bytes"]
        ):
            raise ValueError("Raw cultural body changed after source verification")
        body = json.loads(raw)
        labels: dict[str, str] = {}
        for row in body["results"]["bindings"]:
            label = row.get("valueLabel", {})
            if (
                row.get("property", {}).get("value", "").endswith("/P136")
                and label.get("xml:lang") == "en"
            ):
                qid = row["value"]["value"].rsplit("/", 1)[1]
                identity = (row["mbid"]["value"], row["artist"]["value"].rsplit("/", 1)[1], qid)
                if identity not in accepted:
                    continue
                if qid in labels and labels[qid] != label["value"]:
                    raise ValueError("Conflicting English labels in one raw source response")
                labels[qid] = label["value"]
        for qid, label in sorted(labels.items()):
            _persist_projection(
                connection,
                pack,
                batch,
                EntityProjection(
                    entity_kind="genre",
                    source_identity=ExternalIdentity(namespace="wikidata", value=qid),
                    names=(NameClaim(kind="primary", value=label, language_tag="en"),),
                    identifiers=(
                        IdentifierClaim(
                            type_key="wikidata_genre_qid", namespace="wikidata", value=qid
                        ),
                    ),
                ),
            )


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "artists",
        "release_groups",
        "recordings",
        "entity_claims",
        "artist_genre_evidence",
        "entity_identifiers",
        "entity_names",
        "provenance_records",
        "search_documents",
    )
    return {
        table: int(connection.execute("SELECT count(*) FROM " + table).fetchone()[0])  # noqa: S608 -- fixed table inventory.
        for table in tables
    }


def _observations(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return sorted(
        tuple(row)
        for row in connection.execute(
            """WITH mb AS(SELECT DISTINCT i.entity_id,i.normalized_value FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE t.type_key='musicbrainz_artist_id')
           SELECT mb.normalized_value,json_extract(c.normalized_value_json,'$.target.value'),
                  s.source_key,p.artifact_sha256 FROM entity_claims c
           JOIN mb ON mb.entity_id=c.entity_id JOIN provenance_records p ON p.id=c.provenance_id
           JOIN data_sources s ON s.id=p.source_id
           WHERE c.claim_type='wikidata_relation' AND c.claim_key='genre'
           ORDER BY 1,2,3,4"""
        )
    )


def _neighbors(path: Path) -> dict[str, Any]:
    store = PublicArtistNavigationStore(path)
    result = {}
    with closing(sqlite3.connect(path)) as connection:
        artist_rows = connection.execute(
            """SELECT DISTINCT i.entity_id,i.normalized_value FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE t.type_key='musicbrainz_artist_id' ORDER BY i.normalized_value"""
        ).fetchall()
        native = {int(row[0]): str(row[1]) for row in artist_rows}
        for entity, mbid in artist_rows:
            offset = 0
            related = []
            while True:
                response = store._related_artists_sync(entity, offset, PAGE_SIZE)
                related.extend(native[r.artist.entity_id] for r in response.related)
                if len(response.related) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
            result[mbid] = {
                "name": response.artist.name,
                "name_status": response.artist.name_status,
                "neighbors": sorted(related),
                "neighbor_count": len(related),
            }
    return result


def _nameless_artist_qids(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """SELECT DISTINCT i.entity_id,i.normalized_value FROM entity_identifiers i
           JOIN identifier_types t ON t.id=i.identifier_type_id
           JOIN artists a ON a.id=i.entity_id WHERE t.type_key='wikidata_artist_qid'
           AND NOT EXISTS(SELECT 1 FROM entity_names n WHERE n.entity_id=a.id) ORDER BY 2"""
    ).fetchall()
    if len(rows) != EXPECTED_NAMELESS or any(
        connection.execute("SELECT 1 FROM search_documents WHERE entity_id=?", (row[0],)).fetchone()
        for row in rows
    ):
        raise ValueError("Unobserved artist names were fabricated or source missingness differs")
    return [str(row[1]) for row in rows]


def _validate_neighbors(neighbors: dict[str, Any]) -> None:
    if (
        len(neighbors) != EXPECTED_ARTISTS
        or sum(bool(r["neighbors"]) for r in neighbors.values()) != EXPECTED_SUPPORTED_NEIGHBORS
    ):
        raise ValueError("Full source navigation denominator differs")
    if sum(r["neighbor_count"] for r in neighbors.values()) != EXPECTED_DIRECTED_EDGES:
        raise ValueError("Source observed co-genre edge count differs")


def _build(
    path: Path,
    source: PortableMusicBrainzCreditSource,
    packs: tuple[CulturalPack, ...],
    *,
    wikidata_first: bool,
) -> dict[str, Any]:
    hydration = MusicBrainzReleaseHydrationArtifact.model_validate_json(
        source.hydration_artifact_json
    )
    credit = ArtistCreditRefreshCandidateArtifact.model_validate_json(source.credit_artifact_json)
    release_ids, recording_ids = native_credits._normalized_ids(hydration)
    cache = {
        p.endpoint: CachedResponse.model_validate_json(p.cached_response_json)
        for p in source.projections
    }
    relations = native_credits._validate_credit_partition(
        artifact=credit, release_ids=release_ids, recording_ids=recording_ids, cache=cache
    )
    materialize_hydration_catalog(
        hydration, database_path=path, artifact_sha256=source.hydration_artifact_sha256
    )
    with Database(path).connect() as connection:
        prov = native_credits._credit_provenance(
            connection, source.credit_artifact_sha256, source.hydration_artifact_sha256
        )
        if not wikidata_first:
            native_credits._persist_credits(connection, relations, prov)
        for pack in packs:
            ingest_pack(connection, pack)
        if wikidata_first:
            native_credits._persist_credits(connection, relations, prov)
        before = _table_counts(connection)
        for pack in packs:
            ingest_pack(connection, pack)
        after = _table_counts(connection)
        if before != after:
            raise ValueError("Repeated source projection is not idempotent")
        observations = _observations(connection)
        graph = _normalized_graph(connection)
        if (
            after["artists"],
            after["release_groups"],
            after["recordings"],
            after["entity_claims"],
            after["artist_genre_evidence"],
        ) != (433, 87, 1031, 287, 278):
            raise ValueError("Full retained source denominator differs")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Full cultural catalog foreign-key check failed")
        nameless = _nameless_artist_qids(connection)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
    neighbors = _neighbors(path)
    _validate_neighbors(neighbors)
    policy = CertifiedPublicMembershipAdapterPolicy(
        direct_selectors=tuple(
            CertifiedPublicDirectSelector(
                source="wikidata",
                facet="wikidata_p136",
                source_key_prefix=p.source_key,
                method_key="wikidata_p136",
                required_license="CC0-1.0",
            )
            for p in packs
        )
    )
    consumer_policy = source_policy_for_adapter(policy)
    adapted = adapt_certified_public_membership_input(path, policy)
    verify_certified_public_membership_receipt(
        adapted.approved_input, adapted.receipt, path, policy
    )
    for suffix, value in (("approved-input", adapted.approved_input), ("receipt", adapted.receipt)):
        path.with_suffix("." + suffix + ".json").write_text(value.model_dump_json(indent=2) + "\n")
    return {
        "counts": after,
        "projection_idempotent": True,
        "graph": graph,
        "source_observations": observations,
        "neighbors": neighbors,
        "nameless_artist_qids": nameless,
        "adapter_policy": policy.model_dump(mode="json"),
        "consumer_source_families": sorted(consumer_policy.allowed_direct_sources),
        "consumer_source_facets": sorted(consumer_policy.allowed_direct_facets),
        "adapter": {
            "direct_rows": adapted.receipt.direct_row_count,
            "genres": len(adapted.approved_input.public_model_input.genres),
            "metadata_observations": len(adapted.receipt.metadata_bindings),
            "artifacts": len(adapted.approved_input.public_model_input.artifacts),
        },
    }


def _missingness(packs: tuple[CulturalPack, ...]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for pack in packs:
        matches = {r["musicbrainz_artist_id"]: r for r in pack.artists}
        for nomination in pack.manifest["cohort"]:
            mbid = nomination["artist_mbid"]
            row = rows.setdefault(
                mbid,
                {
                    "musicbrainz_artist_id": mbid,
                    "source_observations": [],
                    "p136_qids": set(),
                    "wikidata_artist_id": None,
                },
            )
            match = matches.get(mbid)
            if match is not None:
                if row["wikidata_artist_id"] not in (None, match["wikidata_artist_id"]):
                    raise ValueError("Sources disagree about exact MBID/QID identity")
                row["wikidata_artist_id"] = match["wikidata_artist_id"]
                row["p136_qids"].update(
                    c["value_qid"] for c in match["claims"] if c["property_id"] == "P136"
                )
            row["source_observations"].append(
                {
                    "source_key": pack.source_key,
                    "matched": match is not None,
                    "english_artist_label_observed": bool(match and match["label"]),
                }
            )
    for row in rows.values():
        row["p136_qids"] = sorted(row["p136_qids"])
        row["reason"] = (
            "no_exact_source_match"
            if row["wikidata_artist_id"] is None
            else "matched_with_p136"
            if row["p136_qids"]
            else "matched_without_observed_p136"
        )
    return [rows[key] for key in sorted(rows)]


def _core_input(
    core_source: Path, core_pin: str, pack_paths: tuple[Path, ...], output: Path
) -> PortableMusicBrainzCreditSource:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Cultural catalog output must be fresh")
    inputs = (core_source, *pack_paths)
    if any(
        output.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(output.resolve())
        for p in inputs
    ):
        raise ValueError("Cultural catalog inputs and output overlap")
    if any(p.is_symlink() for p in (core_source, *core_source.parents)):
        raise ValueError("Native core source cannot traverse symlinks")
    if (
        core_pin != CORE_SHA
        or core_source.stat().st_size > SOURCE_MAX_BYTES
        or digest(core_source) != core_pin
    ):
        raise ValueError("Native portable core source pin differs")
    return PortableMusicBrainzCreditSource.model_validate_json(core_source.read_bytes())


def build(  # noqa: PLR0913, PLR0917 -- All three physical sources and pins remain explicit.
    core_source: Path,
    core_pin: str,
    cultural_pack: Path,
    cultural_pin: str,
    independent_pack: Path,
    independent_pin: str,
    output: Path,
) -> dict[str, Any]:
    """Atomically build both ordinary ingestion orders on the entire fixed source cohort."""
    source = _core_input(core_source, core_pin, (cultural_pack, independent_pack), output)
    packs = (
        load_pack(cultural_pack, PACKS[0][0], cultural_pin),
        load_pack(independent_pack, PACKS[1][0], independent_pin),
    )
    nominations = _missingness(packs)
    counts = {
        reason: sum(r["reason"] == reason for r in nominations)
        for reason in (
            "no_exact_source_match",
            "matched_with_p136",
            "matched_without_observed_p136",
        )
    }
    if len(nominations) != EXPECTED_NOMINATIONS or tuple(counts.values()) != (62, 78, 10):
        raise ValueError("Predeclared source missingness differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cultural-catalog-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        orders = {}
        for first in (False, True):
            key = "wikidata-first" if first else "musicbrainz-first"
            orders[key] = _build(stage / (key + ".sqlite"), source, packs, wikidata_first=first)
        if orders["musicbrainz-first"]["graph"] != orders["wikidata-first"]["graph"] or (
            orders["musicbrainz-first"]["source_observations"]
            != orders["wikidata-first"]["source_observations"]
        ):
            raise ValueError("Native/source fact graph differs by ingestion order")
        # Compare the public source-neighborhood semantics, not surrogate IDs/timestamps.
        if orders["musicbrainz-first"]["neighbors"] != orders["wikidata-first"]["neighbors"]:
            raise ValueError("Public source neighborhoods differ by ingestion order")
        for pack in packs:
            load_pack(pack.directory, pack.source_key, pack.receipt_sha256)
        (stage / "missingness.json").write_bytes(canonical_json(nominations))
        report = {
            "revision": "cc0-cultural-catalog-v1",
            "license": "CC0-1.0",
            "attribution": "MusicBrainz and Wikidata contributors",
            "core_source_sha256": core_pin,
            "core_custody": "Verified portable safe projections; original HTTP bodies not retained",
            "wikidata_custody": "Native raw SPARQL bodies independently replayed",
            "scope": (
                "Exact P434/P136 and source-qualified English labels only; "
                "other properties remain raw, no hierarchy or inferred memberships"
            ),
            "canonical_capture_order": [p.source_key for p in packs],
            "deduplication": (
                "287 source entity_claim observations;278 canonical direct facts; "
                "9repeat observations are not votes. Canonical suppression has no "
                "second-capture fact fallback. Identifier/name provenance need not "
                "retain every repeated capture."
            ),
            "source": {
                "unique_requested_artists": 150,
                "source_nominations": sum(p.manifest["requested_artist_count"] for p in packs),
                "matched_artists": 88,
                "missingness": counts,
                "source_p136_observations": 287,
                "unique_p136_facts": 278,
                "genre_qids": 151,
            },
            "source_packs": {
                p.source_key: {
                    "receipt_sha256": p.receipt_sha256,
                    "manifest_sha256": digest(p.directory / "manifest.json"),
                    "requested": p.manifest["requested_artist_count"],
                    "matched": len(p.artists),
                }
                for p in packs
            },
            "orders": orders,
            "acquisitions": 0,
            "fits": 0,
            "new_external_cost_usd": 0,
        }
        root = Path(__file__).resolve().parents[3]
        paths = (
            "src/opennoise/pipeline/cultural_catalog.py",
            "src/opennoise/pipeline/artist_identity_replay.py",
            "src/opennoise/models/catalog.py",
            "src/opennoise/catalog/entities.py",
            "src/opennoise/catalog/artist_identity.py",
            "src/opennoise/serving/public/artist_navigation_store.py",
            "src/opennoise/serving/public/artist_membership_adapter.py",
            "src/opennoise/serving/public/membership_export_eligibility.py",
            "src/opennoise/ingest/musicbrainz/artist_credit_catalog_candidate.py",
            "src/opennoise/ingest/musicbrainz/release_hydration.py",
            "src/opennoise/pipeline/portable_foundation.py",
            "scripts/replay_cc0_cultural_catalog.py",
        )
        report["implementation_sha256"] = {p: digest(root / p) for p in paths}
        (stage / "adapter-policy.json").write_bytes(
            canonical_json(orders["musicbrainz-first"]["adapter_policy"])
        )
        report["files"] = {
            p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in stage.iterdir()
        }
        (stage / "report.json").write_bytes(canonical_json(report))
        if sum(p.stat().st_size for p in stage.iterdir()) > MAX_BYTES:
            raise ValueError("Cultural catalog combined32MB output bound exceeded")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Cultural catalog output must remain fresh")
        stage.rename(output)
    return report
