"""Reproduce the typed artist-identity join on retained permissive source evidence.

MusicBrainz input is a verified portable core projection, not retained HTTP body
custody. Wikidata input includes raw SPARQL bodies and is independently replayed.
This bounded regression build never adds genres from MusicBrainz credit metadata.
"""

# ruff: noqa: SLF001 -- reuse existing exact portable/native replay boundaries.
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from opennoise.pipeline.portable_foundation import _verified_cultural
from opennoise.serving.public.artist_navigation_store import PublicArtistNavigationStore

CORE_SHA = "13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba"
CULTURAL_SHA = "df9763aef5b3f5801cc9ef999ecd34b24b97c588dc25679a2adaf8432461cfa5"
MAX_BYTES = 32_000_000
SOURCE_MAX_BYTES = 2_000_000
EXPECTED_OVERLAP = 7
EXPECTED_JOINED_CREDITS = 87


def digest(path: Path) -> str:
    """Return a physical source/output binding."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(connection: sqlite3.Connection) -> tuple[int, int]:
    now = datetime.now(UTC).isoformat()
    policy = connection.execute(
        """INSERT INTO rights_policies
           (policy_key,policy_version,classification,local_only,basis,reviewed_at)
           VALUES ('wikidata-cultural-exact-artist',1,'public_domain',0,
                   'Wikidata CC0 structured data; exact raw capture replay',?)""",
        (now,),
    ).lastrowid
    if policy is None:
        raise RuntimeError("Wikidata policy registration failed")
    for use in ("normalize", "local_search", "display", "embed", "train", "export"):
        connection.execute(
            """INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason)
               VALUES (?,?,'allow','Wikidata structured data CC0')""",
            (policy, use),
        )
    connection.execute(
        "INSERT INTO rights_policy_seals(policy_id,sealed_at) VALUES (?,?)", (policy, now)
    )
    source = connection.execute(
        """INSERT INTO data_sources
           (source_key,name,homepage_url,license_name,license_url,acquisition_kind,default_policy_id)
           VALUES ('wikidata_cultural_exact_artist','Wikidata cultural artist source',
                   'https://query.wikidata.org/sparql','CC0-1.0',
                   'https://www.wikidata.org/wiki/Wikidata:Licensing','user_supplied_local',?)""",
        (policy,),
    ).lastrowid
    if source is None:
        raise RuntimeError("Wikidata source registration failed")
    return source, policy


def _wikidata(
    connection: sqlite3.Connection,
    selected: list[dict[str, Any]],
    manifest: dict[str, Any],
    manifest_sha256: str,
) -> None:
    source, policy = _policy(connection)
    snapshot = connection.execute(
        """INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,
           manifest_sha256,acquired_at,policy_id) VALUES(?,?,'single_artifact',?,?,?)""",
        (
            source,
            "retained:" + manifest["acquired_utc"],
            manifest_sha256,
            manifest["acquired_utc"],
            policy,
        ),
    ).lastrowid
    for batch in manifest["batches"]:
        connection.execute(
            """INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,
               media_type,byte_size,sha256,vault_key,policy_id)
               VALUES(?,?,'Retained raw Wikidata response','application/json',?,?,?,?)""",
            (
                snapshot,
                batch["raw_path"],
                batch["response_bytes"],
                batch["response_sha256"],
                batch["response_sha256"],
                policy,
            ),
        )
    for row in selected:
        batch = next(
            b for b in manifest["batches"] if row["musicbrainz_artist_id"] in b["requested_mbids"]
        )
        projection = EntityProjection(
            entity_kind="artist",
            source_identity=ExternalIdentity(namespace="wikidata", value=row["wikidata_artist_id"]),
            names=(
                NameClaim(
                    kind="primary",
                    value=row["label"] or row["wikidata_artist_id"],
                    language_tag="en" if row["label"] else "und",
                ),
            ),
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
                    target=ExternalIdentity(namespace="wikidata", value=c["value_qid"]),
                    target_kind="genre",
                    rank=None,  # Truthy capture did not retain statement ranks.
                )
                for c in row["claims"]
                if c["property_id"] == "P136"
            ),
        )
        # The record is a derived common projection; artifact_sha256 remains the
        # raw response actually replayed, not a claim that our JSON came upstream.
        prov = connection.execute(
            """INSERT INTO provenance_records
               (source_id,policy_id,snapshot_ref,artifact_sha256,record_fingerprint,
                parser_release_ref,ingest_attempt_ref,observed_at)
               VALUES (?,?,?,?,?,'verified-cultural-to-entity-v1',?,?)""",
            (
                source,
                policy,
                "retained:" + manifest["acquired_utc"],
                batch["response_sha256"],
                hashlib.sha256(projection.model_dump_json().encode()).hexdigest(),
                "offline-identity-replay",
                manifest["acquired_utc"],
            ),
        ).lastrowid
        if prov is None:
            raise RuntimeError("Wikidata provenance registration failed")
        EntityProjector().persist(connection, projection, provenance_id=prov, policy_id=policy)


def _normalized_graph(connection: sqlite3.Connection) -> dict[str, Any]:
    identifiers = list(
        connection.execute(
            """SELECT DISTINCT i.entity_id,t.type_key,i.normalized_value
           FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id
           WHERE (i.namespace='musicbrainz' AND t.type_key IN
             ('musicbrainz_artist_id','musicbrainz_recording_id','musicbrainz_release_id'))
             OR (i.namespace='wikidata' AND t.type_key='wikidata_artist_qid')"""
        )
    )
    native = {int(e): str(v) for e, t, v in identifiers if t != "wikidata_artist_qid"}
    qids = sorted((native[int(e)], v) for e, t, v in identifiers if t == "wikidata_artist_qid")
    claims = sorted(
        tuple(r)
        for r in connection.execute(
            """SELECT DISTINCT a.normalized_value,g.normalized_value,s.source_key,p.policy_key,
                    provenance.artifact_sha256
           FROM artist_genre_evidence e
           JOIN entity_identifiers a ON a.entity_id=e.artist_id
           JOIN identifier_types at ON at.id=a.identifier_type_id
                AND at.type_key='musicbrainz_artist_id'
           JOIN entity_identifiers g ON g.entity_id=e.genre_id
           JOIN identifier_types gt ON gt.id=g.identifier_type_id
                AND gt.type_key='wikidata_genre_qid'
           JOIN rights_policies p ON p.id=e.policy_id
           JOIN provenance_records provenance ON provenance.id=e.provenance_id
           JOIN data_sources s ON s.id=provenance.source_id"""
        )
    )
    credit_rows = sorted(
        (native[int(e)], int(position), native[int(a)], name, joinphrase)
        for e, position, a, name, joinphrase in connection.execute(
            """SELECT e.entity_id,m.position,m.artist_id,m.credited_name,m.join_phrase
           FROM entity_artist_credits e JOIN artist_credit_members m
             ON m.artist_credit_id=e.artist_credit_id"""
        )
    )
    return {"crosswalks": qids, "claims": claims, "ordered_native_credits": credit_rows}


def _build(  # noqa: PLR0913 -- Explicit verified manifest custody accompanies source projections.
    path: Path,
    source: PortableMusicBrainzCreditSource,
    selected: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    wikidata_first: bool,
    manifest_sha256: str,
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
        if wikidata_first:
            _wikidata(connection, selected, manifest, manifest_sha256)
        native_credits._persist_credits(connection, relations, prov)
        if not wikidata_first:
            _wikidata(connection, selected, manifest, manifest_sha256)
        graph = _normalized_graph(connection)
        counts = {
            table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]  # noqa: S608 -- closed constant table names.
            for table in ("artists", "release_groups", "recordings", "artist_genre_evidence")
        }
        if tuple(counts.values()) != (352, 87, 1031, 40):
            raise ValueError("Complete retained-source counts differ")
        if list(connection.execute("PRAGMA foreign_key_check")):
            raise ValueError("Joined catalog has foreign-key violations")
        joined = list(
            connection.execute(
                """SELECT DISTINCT c.entity_id FROM entity_artist_credits c
               JOIN artist_credit_members m ON m.artist_credit_id=c.artist_credit_id
               JOIN artist_genre_evidence e ON e.artist_id=m.artist_id"""
            )
        )
        if len(joined) != EXPECTED_JOINED_CREDITS:
            raise ValueError("Native credit-to-Wikidata genre join differs")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
    # Use the existing display-policy-filtered navigation, not a bypass graph.
    store = PublicArtistNavigationStore(path)
    neighbors = {}
    with sqlite3.connect(path) as connection:
        for entity, mbid in connection.execute(
            """SELECT DISTINCT i.entity_id,i.normalized_value FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE t.type_key='musicbrainz_artist_id'"""
        ):
            response = store._related_artists_sync(entity, 0, 50)
            neighbors[mbid] = len(response.related)
    return {
        "counts": counts,
        "credited_entities_joined": len(joined),
        "normalized_graph": graph,
        "source_shared_genre_neighbor_counts": neighbors,
    }


def _inputs(
    core_source: Path, core_pin: str, cultural_pack: Path, cultural_pin: str
) -> tuple[
    PortableMusicBrainzCreditSource,
    dict[str, Any],
    list[dict[str, Any]],
    set[str],
    list[dict[str, Any]],
]:
    for path in (core_source, cultural_pack):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Replay source paths cannot traverse symlinks")
    if (cultural_pack / "receipt.json").stat().st_size > SOURCE_MAX_BYTES:
        raise ValueError("Cultural receipt cap exceeded")
    if (
        core_pin != CORE_SHA
        or core_source.stat().st_size > SOURCE_MAX_BYTES
        or digest(core_source) != core_pin
    ):
        raise ValueError("Pinned portable CC0 core source differs")
    if cultural_pin != CULTURAL_SHA or digest(cultural_pack / "receipt.json") != cultural_pin:
        raise ValueError("Pinned raw cultural source receipt differs")
    if sum(p.stat().st_size for p in cultural_pack.rglob("*") if p.is_file()) > SOURCE_MAX_BYTES:
        raise ValueError("Cultural input cap exceeded")
    source = PortableMusicBrainzCreditSource.model_validate_json(core_source.read_bytes())
    manifest, evidence = _verified_cultural(cultural_pack)
    credit = ArtistCreditRefreshCandidateArtifact.model_validate_json(source.credit_artifact_json)
    native_artists = {str(m.artist_id) for r in credit.credits for m in r.members}
    selected = [r for r in evidence if r["musicbrainz_artist_id"] in native_artists]
    if len(selected) != EXPECTED_OVERLAP:
        raise ValueError("Exact source overlap differs")
    return source, manifest, evidence, native_artists, selected


def replay(
    core_source: Path, core_pin: str, cultural_pack: Path, cultural_pin: str, output: Path
) -> dict[str, Any]:
    """Build two fresh full catalogs and prove exact native graph order invariance."""
    if output.exists() or output.is_symlink():
        raise FileExistsError("Replay output must be fresh")
    source, manifest, evidence, native_artists, selected = _inputs(
        core_source, core_pin, cultural_pack, cultural_pin
    )
    for path in (core_source, cultural_pack):
        if output.resolve().is_relative_to(path.resolve()) or path.resolve().is_relative_to(
            output.resolve()
        ):
            raise ValueError("Output overlaps a source")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".artist-identity-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        orders = {}
        for first in (False, True):
            name = "wikidata-first" if first else "musicbrainz-first"
            orders[name] = _build(
                staging / (name + ".sqlite"),
                source,
                selected,
                manifest,
                wikidata_first=first,
                manifest_sha256=digest(cultural_pack / "manifest.json"),
            )
        if (
            orders["musicbrainz-first"]["normalized_graph"]
            != orders["wikidata-first"]["normalized_graph"]
        ):
            raise ValueError("Normalized native identity/claim/credit graphs differ by order")
        report = {
            "revision": "cc0-exact-artist-identity-replay-v1",
            "license": "CC0-1.0",
            "attribution": "MusicBrainz and Wikidata contributors",
            "source": {
                "core_portable_projection_sha256": core_pin,
                "cultural_receipt_sha256": cultural_pin,
                "core_custody": "verified safe projections; original HTTP bodies not retained",
                "wikidata_custody": "native raw SPARQL replay",
                "wikidata_statement_ranks": "not retained; explicit null in derived claims",
                "requested_cultural_artists": manifest["requested_artist_count"],
                "matched_cultural_artists": len(evidence),
                "native_artists": len(native_artists),
                "exact_overlap": len(selected),
                "core_artists_without_observed_p136": len(native_artists) - len(selected),
                "unjoined_matched_cultural_artists": len(evidence) - len(selected),
            },
            "normalized_graph_sha256": hashlib.sha256(
                canonical_json(orders["musicbrainz-first"]["normalized_graph"])
            ).hexdigest(),
            "orders": {
                k: {key: value for key, value in v.items() if key != "normalized_graph"}
                for k, v in orders.items()
            },
            "databases": {
                p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in staging.iterdir()
            },
            "no_genres_inferred_from_credits": True,
            "acquisitions": 0,
            "new_cost_usd": 0,
        }
        implementation_paths = (
            Path(__file__),
            Path(__file__).parents[1] / "catalog/artist_identity.py",
            Path(__file__).parents[1] / "catalog/entities.py",
            Path(__file__).parents[1] / "catalog/artists.py",
            Path(__file__).parents[1] / "catalog/musicbrainz.py",
            Path(__file__).parents[1] / "models/catalog.py",
            Path(__file__).parents[1] / "serving/public/artist_navigation_store.py",
            Path(__file__).parents[1] / "serving/public/membership_export_eligibility.py",
            Path(native_credits.__file__),
            Path(__file__).parents[3] / "scripts/replay_cc0_artist_identity.py",
        )
        report["implementation_sha256"] = {p.name: digest(p) for p in implementation_paths}
        (staging / "report.json").write_bytes(canonical_json(report) + b"\n")
        if sum(p.stat().st_size for p in staging.iterdir()) > MAX_BYTES:
            raise ValueError("Replay output cap exceeded")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Replay output appeared during build")
        staging.rename(output)
    return report
