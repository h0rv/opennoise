"""Full migrated-catalog regressions for the public export boundary."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar, override

from opennoise.catalog.entities import EntityProjector
from opennoise.models.catalog import EntityProjection, ExternalIdentity, NameClaim, RelationClaim
from opennoise.pipeline.artist_identity_replay import CORE_SHA, CULTURAL_SHA, replay
from opennoise.serving.public.artist_membership import canonical_sha256
from opennoise.serving.public.artist_membership_adapter import (
    CertifiedPublicDirectSelector,
    CertifiedPublicMembershipAdaptation,
    CertifiedPublicMembershipAdapterPolicy,
    CertifiedPublicMembershipAdapterReceipt,
    CertifiedPublicMetadataSelector,
    adapt_certified_public_membership_input,
    verify_certified_public_membership_receipt,
)

ROOT = Path(__file__).resolve().parents[3]
RAW_SHA = "df1cf4e12a947ff18df1a7bcfb1cfda68e8c30b17e197275f07d4b336f772f19"
POLICY = CertifiedPublicMembershipAdapterPolicy(
    direct_selectors=(
        CertifiedPublicDirectSelector(
            source="wikidata",
            facet="wikidata_p136",
            source_key_prefix="wikidata_cultural_exact_artist",
            method_key="wikidata_p136",
            required_license="CC0-1.0",
        ),
    )
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _suppress(
    connection: sqlite3.Connection,
    kind: str,
    ref: str,
    use: str = "export",
    *,
    action: str = "suppress",
) -> None:
    sequence = 2 if action == "release" else 1
    connection.execute(
        """INSERT INTO suppression_events(target_kind,target_ref,use_kind,event_action,reason,
               effective_at,event_fingerprint) VALUES(?,?,?,?,?,?,?)""",
        (
            kind,
            ref,
            use,
            action,
            "Explicit export regression",
            f"2026-01-0{sequence}T00:00:00Z",
            hashlib.sha256(f"{kind}:{ref}:{use}:{action}:{sequence}".encode()).hexdigest(),
        ),
    )
    connection.commit()


class MembershipExportProvenanceTests(unittest.TestCase):
    """Use every real CC0 claim and the ordinary migrated schema, not table stubs."""

    temp: ClassVar[tempfile.TemporaryDirectory[str]]
    base: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        output = Path(cls.temp.name) / "replay"
        core = (
            ROOT
            / "data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256"
            / f"{CORE_SHA}.json"
        )
        cultural = ROOT / "data/examples/independent-cultural-context"
        replay(core, CORE_SHA, cultural, CULTURAL_SHA, output)
        cls.base = output / "musicbrainz-first.sqlite"
        raw = cultural / "raw/batch-00.json"
        if _hash(raw) != RAW_SHA:
            raise ValueError("real raw source fixture changed")
        with sqlite3.connect(cls.base) as c:
            source, policy, snapshot, observed = c.execute(
                """SELECT DISTINCT p.source_id,p.policy_id,p.snapshot_ref,p.observed_at
                   FROM provenance_records p JOIN data_sources s ON s.id=p.source_id
                   WHERE s.source_key='wikidata_cultural_exact_artist'"""
            ).fetchone()
            ss = c.execute(
                """INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,
                       manifest_sha256,acquired_at,policy_id)
                       VALUES(?,?,'single_artifact',?,?,?)""",
                (source, snapshot, _hash(cultural / "manifest.json"), observed, policy),
            ).lastrowid
            c.execute(
                """INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,
                       byte_size,sha256,vault_key,policy_id) VALUES(?,'raw/batch-00.json',
                       'Retained raw Wikidata response','application/json',?,?,?,?)""",
                (ss, raw.stat().st_size, RAW_SHA, RAW_SHA, policy),
            )

    @override
    def setUp(self) -> None:
        self.path = Path(self.temp.name) / f"{self._testMethodName}.sqlite"
        with sqlite3.connect(self.base) as source, sqlite3.connect(self.path) as target:
            source.backup(target)
        self.c = sqlite3.connect(self.path)
        self.c.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.c.close)
        self.artist, self.genre, self.prov, self.policy = self.c.execute(
            "SELECT artist_id,genre_id,provenance_id,policy_id "
            "FROM artist_genre_evidence ORDER BY id"
        ).fetchone()
        self.qid = self.c.execute(
            """SELECT i.normalized_value FROM entity_identifiers i JOIN identifier_types t
               ON t.id=i.identifier_type_id WHERE i.entity_id=?
               AND t.type_key='wikidata_genre_qid'""",
            (self.genre,),
        ).fetchone()[0]

    def adapt(
        self, policy: CertifiedPublicMembershipAdapterPolicy = POLICY
    ) -> CertifiedPublicMembershipAdaptation:
        """Call the complete public API against the current physical database bytes."""
        self.c.commit()
        return adapt_certified_public_membership_input(self.path, policy)

    def test_real_baseline_40_all_metadata_eligible_and_receipt_replays(self) -> None:
        result = self.adapt()
        self.assertEqual(result.receipt.direct_row_count, 40)
        self.assertEqual(result.receipt.revision, "certified-public-membership-adapter-receipt-v2")
        self.assertTrue(result.receipt.metadata_bindings)
        self.assertEqual(
            {x.artifact_sha256 for x in result.receipt.direct_source_bindings}, {RAW_SHA}
        )
        self.assertEqual(
            {x.source_binding.artifact_sha256 for x in result.receipt.metadata_bindings}, {RAW_SHA}
        )
        self.assertEqual(
            {x.content_sha256 for x in result.approved_input.public_model_input.artifacts},
            {RAW_SHA},
        )
        self.assertTrue(
            all(x.name.startswith("Q") for x in result.approved_input.public_model_input.genres)
        )
        verify_certified_public_membership_receipt(
            result.approved_input, result.receipt, self.path, POLICY
        )

    def test_source_snapshot_artifact_all_export_suppress_and_release(self) -> None:
        source, snapshot, artifact = self.c.execute(
            """SELECT s.source_id,s.id,a.id FROM source_snapshots s JOIN source_artifacts a
               ON a.snapshot_id=s.id WHERE a.sha256=?""",
            (RAW_SHA,),
        ).fetchone()
        for kind, ref in (("source", source), ("snapshot", snapshot), ("artifact", artifact)):
            for use in ("all", "export"):
                with self.subTest(kind=kind, use=use):
                    _suppress(self.c, kind, str(ref), use)
                    with self.assertRaisesRegex(ValueError, "no direct export-authorized"):
                        self.adapt()
                    _suppress(self.c, kind, str(ref), use, action="release")
                    self.assertEqual(self.adapt().receipt.direct_row_count, 40)

    def test_entity_provenance_suppression_only_removes_affected_claims(self) -> None:
        for kind, ref, column in (
            ("entity", self.artist, "artist_id"),
            ("provenance", self.prov, "provenance_id"),
        ):
            with self.subTest(kind=kind):
                removed = self.c.execute(
                    "SELECT count(*) FROM artist_genre_evidence WHERE "
                    "(artist_id=? AND ?='artist_id') OR (provenance_id=? AND ?='provenance_id')",
                    (ref, column, ref, column),
                ).fetchone()[0]
                _suppress(self.c, kind, str(ref))
                result = self.adapt()
                self.assertLessEqual(result.receipt.direct_row_count, 40 - removed)
                # Some shared genre IDs have only this provenance observation;
                # suppressing it also removes other claims that cannot export a genre ID.
                self.assertTrue(
                    all(x.provenance_id != ref for x in result.receipt.metadata_bindings)
                    if kind == "provenance"
                    else True
                )
                _suppress(self.c, kind, str(ref), action="release")

    def test_claim_refs_link_default_unresolved_generic_relation_and_exact_evidence(self) -> None:
        projection = EntityProjection(
            entity_kind="artist",
            source_identity=ExternalIdentity(namespace="wikidata", value="Q99999999"),
            names=(NameClaim(kind="primary", value="Synthetic suppression subject"),),
            claims=(
                RelationClaim(
                    property_key="genre",
                    target=ExternalIdentity(namespace="wikidata", value=self.qid),
                ),
            ),
        )
        artist = (
            EntityProjector()
            .persist(self.c, projection, provenance_id=self.prov, policy_id=self.policy)
            .target_id
        )
        claim = self.c.execute(
            "SELECT id,normalized_value_json FROM entity_claims WHERE entity_id=?", (artist,)
        ).fetchone()
        self.assertEqual(json.loads(claim[1])["target_kind"], "unresolved")
        self.assertEqual(self.adapt().receipt.direct_row_count, 41)
        _suppress(self.c, "claim", f"entity_claims:{claim[0]}")
        self.assertEqual(self.adapt().receipt.direct_row_count, 40)
        _suppress(self.c, "claim", f"entity_claims:{claim[0]}", action="release")
        evidence = self.c.execute(
            "SELECT id FROM artist_genre_evidence WHERE artist_id=?", (artist,)
        ).fetchone()[0]
        _suppress(self.c, "claim", f"artist_genre_evidence:{evidence}")
        self.assertEqual(self.adapt().receipt.direct_row_count, 40)

    def test_bare_or_unknown_claim_namespace_fails_closed(self) -> None:
        for ref in ("1", "relation:1", "entity_claims:01"):
            with self.subTest(ref=ref):
                _suppress(self.c, "claim", ref)
                with self.assertRaisesRegex(ValueError, "unsupported or ambiguous"):
                    self.adapt()
                _suppress(self.c, "claim", ref, action="release")

    def test_same_entity_multiple_eligible_qids_is_ambiguous(self) -> None:
        self.c.execute(
            """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,
                 normalized_value,provenance_id) SELECT entity_id,identifier_type_id,namespace,
                 'Q99999998','Q99999998',provenance_id FROM entity_identifiers i
                 JOIN identifier_types t ON t.id=i.identifier_type_id
                 WHERE i.entity_id=? AND t.type_key='wikidata_genre_qid' LIMIT 1""",
            (self.genre,),
        )
        with self.assertRaisesRegex(ValueError, "ambiguous eligible"):
            self.adapt()

    def test_same_exact_qid_on_two_entities_or_foreign_kind_is_rejected(self) -> None:
        for kind in ("artist", "genre"):
            with self.subTest(kind=kind):
                self.c.execute("SAVEPOINT duplicate_identity")
                second = self.c.execute(
                    "INSERT INTO catalog_entities(entity_kind) VALUES(?)", (kind,)
                ).lastrowid
                if kind == "artist":
                    self.c.execute("INSERT INTO artists(id) VALUES(?)", (second,))
                else:
                    self.c.execute(
                        "INSERT INTO genres(id,slug,name) VALUES(?,'duplicate','duplicate')",
                        (second,),
                    )
                self.c.execute(
                    """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,
                         normalized_value,provenance_id) SELECT ?,identifier_type_id,namespace,
                         value,normalized_value,provenance_id FROM entity_identifiers i
                         JOIN identifier_types t ON t.id=i.identifier_type_id
                         WHERE i.entity_id=? AND t.type_key='wikidata_genre_qid' LIMIT 1""",
                    (second, self.genre),
                )
                self.c.commit()
                with self.assertRaisesRegex(ValueError, "wrong entity-kind|multiple entities"):
                    self.adapt()
                # Restore a fresh physical catalog for the second independent case.
                self.c.close()
                with sqlite3.connect(self.base) as source, sqlite3.connect(self.path) as target:
                    source.backup(target)
                self.c = sqlite3.connect(self.path)
                self.addCleanup(self.c.close)

    def test_artist_mbid_and_qid_cannot_collapse_two_catalog_entities(self) -> None:
        for type_key in ("musicbrainz_artist_id", "wikidata_artist_qid"):
            with self.subTest(type_key=type_key):
                other = self.c.execute(
                    "INSERT INTO catalog_entities(entity_kind) VALUES('artist')"
                ).lastrowid
                self.c.execute("INSERT INTO artists(id) VALUES(?)", (other,))
                self.c.execute(
                    """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,
                         normalized_value,provenance_id) SELECT ?,identifier_type_id,namespace,
                         value,normalized_value,provenance_id FROM entity_identifiers i
                         JOIN identifier_types t ON t.id=i.identifier_type_id
                         WHERE i.entity_id=? AND t.type_key=? AND i.provenance_id=? LIMIT 1""",
                    (other, self.artist, type_key, self.prov),
                )
                with self.assertRaisesRegex(ValueError, "multiple entities|ambiguously"):
                    self.adapt()
                self.c.close()
                with sqlite3.connect(self.base) as source, sqlite3.connect(self.path) as target:
                    source.backup(target)
                self.c = sqlite3.connect(self.path)
                self.addCleanup(self.c.close)

    def metadata_source(self, *, allow: bool) -> tuple[int, int, str]:
        """Register an explicit synthetic independent observation with its own rights."""
        c = self.c
        policy = c.execute(
            """INSERT INTO rights_policies(
                   policy_key,policy_version,classification,local_only,basis)
               VALUES('metadata-fixture',1,'public_domain',0,'Synthetic metadata rights fixture')"""
        ).lastrowid
        c.execute(
            """INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason)
               VALUES(?,'export',?,'Explicit synthetic source decision')""",
            (policy, "allow" if allow else "deny"),
        )
        c.execute(
            "INSERT INTO rights_policy_permissions(policy_id,use_kind,decision,reason) "
            "VALUES(?,'normalize','allow','Explicit synthetic normalization permission')",
            (policy,),
        )
        c.execute(
            "INSERT INTO rights_policy_seals(policy_id,sealed_at) VALUES(?,'2026-01-01T00:00:00Z')",
            (policy,),
        )
        source = c.execute(
            """INSERT INTO data_sources(source_key,name,license_name,default_policy_id)
               VALUES('wikidata_metadata_fixture','Synthetic metadata source','CC0-1.0',?)""",
            (policy,),
        ).lastrowid
        ss = c.execute(
            """INSERT INTO source_snapshots(source_id,snapshot_ref,snapshot_kind,
                   manifest_sha256,acquired_at,policy_id)
                   VALUES(?,'synthetic-metadata','single_artifact',
                   ?,'2026-01-01T00:00:00Z',?)""",
            (source, "a" * 64, policy),
        ).lastrowid
        artifact_sha = "b" * 64
        c.execute(
            """INSERT INTO source_artifacts(snapshot_id,artifact_ref,logical_name,media_type,
                   byte_size,sha256,vault_key,policy_id)
                   VALUES(?,'synthetic.json','Synthetic metadata',
                   'application/json',1,?,?,?)""",
            (ss, artifact_sha, artifact_sha, policy),
        )
        prov = c.execute(
            """INSERT INTO provenance_records(source_id,policy_id,snapshot_ref,artifact_sha256,
                   record_fingerprint,parser_release_ref,ingest_attempt_ref,observed_at)
                   VALUES(?,?,'synthetic-metadata',?,?,'test','test','2026-01-01T00:00:00Z')""",
            (source, policy, artifact_sha, "c" * 64),
        ).lastrowid
        c.execute(
            """INSERT INTO entity_names(entity_id,name_kind,name,language_tag,is_preferred,
                   provenance_id,fingerprint)
                   VALUES(?,'primary','Synthetic qualified genre','und',1,?,?)""",
            (self.genre, prov, "d" * 64),
        )
        if prov is None or source is None:
            raise AssertionError("Synthetic metadata source missing")
        return prov, source, artifact_sha

    def metadata_policy(self) -> CertifiedPublicMembershipAdapterPolicy:
        """Explicitly admit this same-family source, never infer from a key's spelling."""
        return CertifiedPublicMembershipAdapterPolicy(
            direct_selectors=POLICY.direct_selectors,
            metadata_selectors=(
                CertifiedPublicMetadataSelector(
                    source="wikidata",
                    source_key_prefix="wikidata_metadata_fixture",
                ),
            ),
        )

    def test_hidden_metadata_never_inherits_open_claim_rights(self) -> None:
        prov, _, _ = self.metadata_source(allow=False)
        self.c.execute(
            "UPDATE genres SET name='Synthetic qualified genre' WHERE id=?", (self.genre,)
        )
        result = self.adapt(self.metadata_policy())
        self.assertEqual(result.receipt.direct_row_count, 40)
        self.assertNotIn("Synthetic qualified genre", result.model_dump_json())
        self.assertFalse(any(x.provenance_id == prov for x in result.receipt.metadata_bindings))

    def test_private_or_suppressed_conflicting_owner_remains_an_identity_veto(self) -> None:
        prov, _, _ = self.metadata_source(allow=False)
        for suppress_owner in (False, True):
            with self.subTest(suppress_owner=suppress_owner):
                other = self.c.execute(
                    "INSERT INTO catalog_entities(entity_kind) VALUES('genre')"
                ).lastrowid
                self.c.execute(
                    "INSERT INTO genres(id,slug,name) VALUES(?,'conflict','Private fixture')",
                    (other,),
                )
                self.c.execute(
                    """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,
                         normalized_value,provenance_id)
                         SELECT ?,identifier_type_id,namespace,value,
                         normalized_value,? FROM entity_identifiers i JOIN identifier_types t
                         ON t.id=i.identifier_type_id WHERE i.entity_id=?
                         AND t.type_key='wikidata_genre_qid' LIMIT 1""",
                    (other, prov, self.genre),
                )
                if suppress_owner:
                    _suppress(self.c, "entity", str(other))
                with self.assertRaisesRegex(ValueError, "multiple entities|ambiguously"):
                    self.adapt(self.metadata_policy())
                self.c.close()
                with sqlite3.connect(self.base) as source, sqlite3.connect(self.path) as target:
                    source.backup(target)
                self.c = sqlite3.connect(self.path)
                self.addCleanup(self.c.close)
                if not suppress_owner:
                    prov, _, _ = self.metadata_source(allow=False)

    def test_private_conflicting_id_on_same_entity_is_not_hidden_by_export_filter(self) -> None:
        prov, _, _ = self.metadata_source(allow=False)
        self.c.execute(
            """INSERT INTO entity_identifiers(entity_id,identifier_type_id,namespace,value,
                 normalized_value,provenance_id) SELECT entity_id,identifier_type_id,namespace,
                 'Q99999997','Q99999997',? FROM entity_identifiers i JOIN identifier_types t
                 ON t.id=i.identifier_type_id WHERE i.entity_id=?
                 AND t.type_key='wikidata_genre_qid' LIMIT 1""",
            (prov, self.genre),
        )
        with self.assertRaisesRegex(ValueError, "ambiguous eligible"):
            self.adapt(self.metadata_policy())

    def test_used_metadata_artifact_is_bound_and_suppression_restores_identity_label(self) -> None:
        prov, source, artifact_sha = self.metadata_source(allow=True)
        self.assertNotIn("Synthetic qualified genre", self.adapt().model_dump_json())
        result = self.adapt(self.metadata_policy())
        self.assertIn("Synthetic qualified genre", result.model_dump_json())
        self.assertIn(
            artifact_sha,
            {x.content_sha256 for x in result.approved_input.public_model_input.artifacts},
        )
        names = [x for x in result.receipt.metadata_bindings if x.field == "name"]
        self.assertEqual(
            [(x.value, x.provenance_id) for x in names], [("Synthetic qualified genre", prov)]
        )
        _suppress(self.c, "source", str(source))
        restricted = self.adapt(self.metadata_policy())
        self.assertEqual(restricted.receipt.direct_row_count, 40)
        self.assertNotIn("Synthetic qualified genre", restricted.model_dump_json())
        self.assertNotIn(
            artifact_sha,
            {x.content_sha256 for x in restricted.approved_input.public_model_input.artifacts},
        )
        with self.assertRaisesRegex(ValueError, "do not reproduce"):
            verify_certified_public_membership_receipt(
                result.approved_input, result.receipt, self.path, self.metadata_policy()
            )

    def test_resealed_receipt_cannot_omit_metadata_policy_binding(self) -> None:
        receipt = self.adapt().receipt.model_dump(mode="python", exclude={"output_sha256"})
        receipt["metadata_bindings"] = receipt["metadata_bindings"][:-1]
        with self.assertRaisesRegex(ValueError, "metadata/export-policy binding"):
            CertifiedPublicMembershipAdapterReceipt.model_validate(
                {**receipt, "output_sha256": canonical_sha256(receipt)}
            )

    def test_v1_receipt_does_not_gain_v2_certification_by_relabeling(self) -> None:
        receipt = self.adapt().receipt.model_dump(mode="json")
        receipt["revision"] = "certified-public-membership-adapter-receipt-v1"
        with self.assertRaises(ValueError):
            CertifiedPublicMembershipAdapterReceipt.model_validate(receipt)
        receipt["revision"] = "certified-public-membership-adapter-receipt-v2"
        del receipt["metadata_bindings"]
        with self.assertRaises(ValueError):
            CertifiedPublicMembershipAdapterReceipt.model_validate(receipt)

    def test_raw_catalog_name_never_substitutes_for_source_name(self) -> None:
        # The mutable convenience field is not a provenance-qualified observation.
        self.c.execute(
            "UPDATE genres SET name='Restricted descriptive label' WHERE id=?", (self.genre,)
        )
        result = self.adapt()
        self.assertNotIn(
            "Restricted descriptive label",
            {x.name for x in result.approved_input.public_model_input.genres},
        )

    def run_cli(self, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        """Run the ordinary adapter CLI with physically pinned real fixture bytes."""
        policy = Path(self.temp.name) / f"{self._testMethodName}-policy.json"
        policy.write_text(POLICY.model_dump_json(indent=2) + "\n")
        self.c.commit()
        return subprocess.run(  # noqa: S603 -- Fixed local interpreter and checked CLI; extra args are test literals.
            [
                sys.executable,
                str(ROOT / "scripts/adapt_public_artist_membership_input.py"),
                "--database",
                str(self.path),
                "--database-sha256",
                _hash(self.path),
                "--policy",
                str(policy),
                "--policy-sha256",
                _hash(policy),
                "--output",
                str(output),
                *extra,
            ],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_pinned_fresh_atomic_output_and_failure_paths(self) -> None:
        output = Path(self.temp.name) / "cli-approved"
        result = self.run_cli(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            {x.name for x in output.iterdir()}, {"approved-input.json", "receipt.json"}
        )
        self.assertEqual(json.loads(result.stdout)["direct_row_count"], 40)
        receipt = CertifiedPublicMembershipAdapterReceipt.model_validate_json(
            (output / "receipt.json").read_bytes()
        )
        self.assertEqual(receipt.database_file_sha256, _hash(self.path))
        again = self.run_cli(output)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("must be fresh", again.stderr)
        wrong = Path(self.temp.name) / "cli-wrong-pin"
        failed = self.run_cli(wrong, "--database-sha256", "0" * 64)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(wrong.exists())
        mixed = Path(self.temp.name) / "cli-mixed"
        failed = self.run_cli(mixed, "--receipt", str(mixed / "other.json"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(mixed.exists())
        before = _hash(self.path)
        alias = Path(self.temp.name) / "cli-alias"
        failed = self.run_cli(alias, "--approved-input", str(self.path))
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(_hash(self.path), before)
        self.assertFalse(alias.exists())

    def test_cli_suppression_keeps_source_rows_but_publishes_no_approved_artifact(self) -> None:
        source = self.c.execute(
            "SELECT source_id FROM provenance_records WHERE id=?", (self.prov,)
        ).fetchone()[0]
        _suppress(self.c, "source", str(source), "all")
        output = Path(self.temp.name) / "cli-suppressed"
        failed = self.run_cli(output)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("no direct export-authorized", failed.stderr)
        self.assertFalse(output.exists())
        self.assertEqual(
            self.c.execute("SELECT count(*) FROM artist_genre_evidence").fetchone()[0], 40
        )

    def test_unbound_sqlite_sidecars_fail_closed(self) -> None:
        self.c.commit()
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(self.path) + suffix)
                sidecar.write_bytes(b"Unbound sidecar fixture")
                try:
                    with self.assertRaisesRegex(ValueError, "without SQLite sidecars"):
                        self.adapt()
                finally:
                    sidecar.unlink()

    def test_real_wal_database_requires_checkpointed_single_file(self) -> None:
        self.c.commit()
        self.assertEqual(self.c.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        self.c.execute(
            "UPDATE genres SET name='Synthetic WAL convenience name' WHERE id=?", (self.genre,)
        )
        self.c.commit()
        self.assertGreater(Path(str(self.path) + "-wal").stat().st_size, 0)
        with self.assertRaisesRegex(ValueError, "without SQLite sidecars"):
            self.adapt()
        self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        self.assertEqual(self.c.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
        self.assertEqual(self.adapt().receipt.direct_row_count, 40)

    def test_uri_special_filename_reads_the_exact_pinned_database(self) -> None:
        unusual = Path(self.temp.name) / "catalog ?# literal.sqlite"
        self.c.commit()
        with sqlite3.connect(self.path) as source, sqlite3.connect(unusual) as target:
            source.backup(target)
        result = adapt_certified_public_membership_input(unusual, POLICY)
        self.assertEqual(result.receipt.direct_row_count, 40)
        self.assertEqual(result.receipt.database_file_sha256, _hash(unusual))

    def test_metadata_source_family_cannot_implicitly_expand_direct_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "declared direct source families"):
            CertifiedPublicMembershipAdapterPolicy(
                direct_selectors=POLICY.direct_selectors,
                metadata_selectors=(
                    CertifiedPublicMetadataSelector(
                        source="musicbrainz", source_key_prefix="musicbrainz_"
                    ),
                ),
            )
