"""Read-only, source-qualified metadata custody for public export and display.

Claim suppression refs are explicitly namespaced in the v2 adapter contract.
No bare numeric claim ID is interpreted as either of the independent tables.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import sqlite3
from uuid import UUID

from opennoise.catalog.artist_identity import resolve_artist
from opennoise.models.catalog import IdentifierClaim


def _validate_identifier(value: str, type_key: str, namespace: str) -> None:
    if namespace == "wikidata":
        valid = bool(re.fullmatch(r"Q[1-9][0-9]*", value))
    elif type_key == "musicbrainz_artist_id":
        try:
            valid = str(UUID(value)) == value
        except ValueError:
            valid = False
    else:
        valid = bool(value.strip())
    if not valid:
        raise ValueError("export identifier is not a canonical typed identity")


class ExportEligibility:
    """Share source custody checks with explicit use permissions; export remains default."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        source_families: tuple[tuple[str, str], ...] | None,
        *,
        use_kind: Literal["export", "display"] = "export",
    ) -> None:
        """Freeze active suppressions for the explicit use in this read-only operation."""
        if use_kind not in ("export", "display"):
            raise ValueError("unsupported metadata eligibility use")
        if use_kind == "export" and source_families is None:
            raise ValueError("export eligibility requires declared source families")
        self.use_kind = use_kind
        self.connection = connection
        self.source_families = source_families
        self.suppressed = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT target_kind,target_ref FROM active_suppressions "
                "WHERE use_kind IN ('all',?)",
                (use_kind,),
            )
        }
        for kind, ref in self.suppressed:
            if (
                use_kind == "export"
                and kind == "claim"
                and not re.fullmatch(r"(?:entity_claims|artist_genre_evidence):[1-9][0-9]*", ref)
            ):
                raise ValueError("unsupported or ambiguous export claim suppression reference")
        self._identities: set[tuple[str, str, str]] = set()
        self._chains: dict[int, dict[str, object] | None] = {}

    def blocked(self, kind: str, value: int) -> bool:
        """Read the established numeric source/entity/provenance/artifact refs."""
        return (kind, str(value)) in self.suppressed

    def chain(self, provenance_id: int) -> dict[str, object] | None:
        """Return one exact CC0 source chain authorized for the selected use."""
        if provenance_id in self._chains:
            return self._chains[provenance_id]
        rows = self.connection.execute(
            """SELECT p.id AS provenance_id,p.source_id,p.policy_id,
                      s.source_key,s.license_name,r.policy_key,r.policy_version,
                      r.classification,r.local_only,ss.id AS snapshot_id,
                      ss.snapshot_ref,ss.manifest_sha256,a.id AS artifact_id,
                      a.artifact_ref,a.sha256 AS artifact_sha256
               FROM provenance_records p JOIN data_sources s ON s.id=p.source_id
               JOIN rights_policies r ON r.id=p.policy_id
               JOIN source_snapshots ss ON ss.source_id=p.source_id
                    AND ss.snapshot_ref=p.snapshot_ref AND ss.policy_id=p.policy_id
               JOIN source_artifacts a ON a.snapshot_id=ss.id
                    AND a.sha256=p.artifact_sha256 AND a.policy_id=p.policy_id
               WHERE p.id=? AND r.classification='public_domain' AND r.local_only=0
                    AND s.license_name='CC0-1.0'
                    AND EXISTS(SELECT 1 FROM active_rights_policy_permissions permission
                        WHERE permission.policy_id=p.policy_id
                        AND permission.use_kind=? AND permission.decision='allow')""",
            (provenance_id, self.use_kind),
        ).fetchall()
        eligible: list[dict[str, object]] = [
            dict(row)
            for row in rows
            if not any(
                self.blocked(kind, int(str(row[key])))
                for kind, key in (
                    ("source", "source_id"),
                    ("provenance", "provenance_id"),
                    ("snapshot", "snapshot_id"),
                    ("artifact", "artifact_id"),
                )
            )
        ]
        if len(eligible) > 1:
            raise ValueError("export observation resolves to ambiguous source artifacts")
        result = eligible[0] if eligible else None
        if result is not None and self.source_families is not None:
            families = {
                family
                for prefix, family in self.source_families
                if str(result["source_key"]).startswith(prefix)
            }
            if len(families) > 1:
                raise ValueError("export source has ambiguous declared metadata family")
            if not families:
                result = None
            else:
                result["source_family"] = next(iter(families))
        self._chains[provenance_id] = result
        return result

    def _consistent_genre_qids(self, entity_id: int) -> None:
        rows = self.connection.execute(
            """SELECT t.type_key,i.namespace,i.normalized_value FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id WHERE i.entity_id=?
               AND (t.type_key='wikidata_qid' OR t.type_key GLOB 'wikidata_*_qid')""",
            (entity_id,),
        ).fetchall()
        for row in rows:
            if row["namespace"] != "wikidata" or row["type_key"] not in (
                "wikidata_qid",
                "wikidata_genre_qid",
            ):
                raise ValueError("eligible exact identity has a wrong entity-kind binding")
            _validate_identifier(str(row["normalized_value"]), "wikidata_genre_qid", "wikidata")
        if len({row["normalized_value"] for row in rows}) > 1:
            raise ValueError("export entity has ambiguous eligible exact identifiers")

    def _unique_identity(self, entity_id: int, type_key: str, namespace: str, value: str) -> None:
        key = (type_key, namespace, value)
        if key in self._identities:
            return
        expected_kind = (
            "artist" if type_key in ("musicbrainz_artist_id", "wikidata_artist_qid") else "genre"
        )
        if expected_kind == "artist":
            # Reuse the production resolver's private-observation ambiguity gate,
            # including generic legacy aliases; custody is still independently checked below.
            resolved = resolve_artist(
                self.connection,
                (
                    IdentifierClaim(
                        type_key=type_key,
                        namespace=namespace,
                        value=value,
                    ),
                ),
            )
            if resolved != entity_id:
                raise ValueError("eligible exact identity resolves to multiple entities")
            self._identities.add(key)
            return
        self._consistent_genre_qids(entity_id)
        rows = self.connection.execute(
            """SELECT i.entity_id,i.provenance_id,t.type_key,e.entity_kind
               FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id
               JOIN catalog_entities e ON e.id=i.entity_id
               WHERE i.namespace=? AND i.normalized_value=? AND (
                   t.type_key='source_id' OR t.type_key='wikidata_qid'
                   OR t.type_key GLOB 'wikidata_*_qid' OR t.type_key GLOB 'musicbrainz_*')""",
            (namespace, value),
        )
        owners = {entity_id}
        for row in rows:
            allowed = {type_key, "wikidata_qid"} if namespace == "wikidata" else {type_key}
            if type_key == "musicbrainz_artist_id":
                allowed.add("source_id")
            if row["entity_kind"] != expected_kind or row["type_key"] not in allowed:
                raise ValueError("eligible exact identity has a wrong entity-kind binding")
            owners.add(int(row["entity_id"]))
        if len(owners) != 1:
            raise ValueError("eligible exact identity resolves to multiple entities")
        self._identities.add(key)

    def identifier(
        self, entity_id: int, type_key: str, namespace: str
    ) -> tuple[str, tuple[dict[str, object], ...]] | None:
        """Resolve one eligible canonical typed identity; repeated observations are allowed."""
        if self.blocked("entity", entity_id):
            return None
        rows = self.connection.execute(
            """SELECT i.normalized_value,i.namespace,i.provenance_id
               FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE i.entity_id=? AND t.type_key=? ORDER BY i.id""",
            (entity_id, type_key),
        ).fetchall()
        # Hidden/suppressed observations can veto an unsafe identity join but
        # never supply exported values or custody. Do not repair duplicates by filtering.
        if len({(row["namespace"], row["normalized_value"]) for row in rows}) > 1:
            raise ValueError("export entity has ambiguous eligible exact identifiers")
        by_value: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            value = str(row["normalized_value"])
            if row["namespace"] != namespace:
                raise ValueError("export identifier has an invalid typed namespace")
            _validate_identifier(value, type_key, namespace)
            self._unique_identity(entity_id, type_key, namespace, value)
            chain = self.chain(int(row["provenance_id"]))
            if chain is None:
                continue
            by_value.setdefault(value, []).append(chain)
        if len(by_value) > 1:
            raise ValueError("export entity has ambiguous eligible exact identifiers")
        if not by_value:
            return None
        value = next(iter(by_value))
        return value, tuple(by_value[value])

    def name(self, entity_id: int) -> tuple[str, dict[str, object]] | None:
        """Choose a deterministic eligible source name, never the catalog default."""
        rows = self.connection.execute(
            f"""SELECT name,provenance_id FROM {self.use_kind}able_entity_names WHERE entity_id=?
               ORDER BY is_preferred DESC,CASE name_kind WHEN 'primary' THEN 0 ELSE 1 END,
                        language_tag,name,provenance_id,id""",  # noqa: S608 -- Validated display/export enum.
            (entity_id,),
        )
        for row in rows:
            chain = self.chain(int(row["provenance_id"]))
            if chain is not None:
                return str(row["name"]), chain
        return None

    def evidence_blocked(self, row: sqlite3.Row, target_qid: str | None) -> bool:
        """Honor exact evidence refs and corresponding generic P136 relation refs."""
        if ("claim", f"artist_genre_evidence:{row['id']}") in self.suppressed:
            return True
        if target_qid is None:
            return False
        claims = self.connection.execute(
            """SELECT id,normalized_value_json FROM entity_claims WHERE entity_id=?
               AND provenance_id=? AND policy_id=? AND claim_key='genre'
               AND claim_type='wikidata_relation'""",
            (row["artist_id"], row["provenance_id"], row["policy_id"]),
        )
        for claim in claims:
            value = json.loads(claim["normalized_value_json"])
            if (
                value.get("target") == {"namespace": "wikidata", "value": target_qid}
                and ("claim", f"entity_claims:{claim['id']}") in self.suppressed
            ):
                return True
        return False
