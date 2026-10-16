"""Synthetic adversarial fixtures for the explicit candidate gate; no real audio."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

from opennoise.deployment import fma_public_candidate as candidate


class PublicCandidateTests(unittest.TestCase):
    """Require complete matching evidence without silently promoting historical exports."""

    @override
    def setUp(self) -> None:
        """Prepare fake native metadata and independently supplied matching tag fixture."""
        self.native: dict[str, Any] = {
            "track_id": 1,
            "artist_id": 2,
            "audio_sha256": hashlib.sha256(b"fake").hexdigest(),
            "audio_bytes": 4,
            "duration_seconds": 1.0,
            "title": "Example",
            "artist_name": "Artist",
            "license_title": "Attribution",
            "license_url": "http://creativecommons.org/licenses/by/4.0/",
            "source_url": "",
            "attribution": "Example — Artist; Attribution",
            "composer": "",
            "copyright_c": "",
            "copyright_p": "",
        }
        self.tags: dict[str, Any] = {
            "streams": [{"tags": {"encoder": "fixture"}}],
            "format": {
                "tags": {
                    "copyright": "http://creativecommons.org/licenses/by/4.0/",
                    "composer": "Supplied Composer",
                    "comment": (
                        "URL: http://freemusicarchive.org/music/example\nCurator: Supplied curator"
                    ),
                }
            },
        }
        credit: dict[str, Any] = {k: self.native[k] for k in candidate.CREDIT_FIELDS}
        credit.update(
            embedded_notices={
                "copyright": self.native["license_url"],
                "composer": "Supplied Composer",
            },
            embedded_source_urls=["http://freemusicarchive.org/music/example"],
            embedded_curators=["Supplied curator"],
        )
        self.decision: dict[str, Any] = {
            "track_id": 1,
            "audio_sha256": self.native["audio_sha256"],
            "status": "include",
            "checks": dict.fromkeys(candidate.CHECKS, True),
            "required_credit_fields": credit,
        }

    def test_matching_projects_only_allowlisted_fields(self) -> None:
        """Unrelated source fields cannot leak through dictionary copying."""
        self.native.update(
            contact_email="private@example.org", payment_url="private", biography="private"
        )
        row = candidate.project_track(self.native, self.decision, self.tags)
        self.assertNotIn("contact_email", row)
        self.assertNotIn("payment_url", row)
        self.assertNotIn("biography", row)
        self.assertEqual(row["source_url"], "")
        self.assertEqual(row["embedded_notices"]["composer"], "Supplied Composer")

    def test_absent_and_conflicting_license_rejected(self) -> None:
        """Missing declarations never become permission; conflicts never prefer permissive CSV."""
        for tags in (
            {},
            {"format": {"tags": {"copyright": "http://creativecommons.org/licenses/by-nc/4.0/"}}},
        ):
            with (
                self.subTest(tags=tags),
                self.assertRaisesRegex(ValueError, "Missing or conflicting"),
            ):
                candidate.project_track(self.native, self.decision, tags)

    def test_review_hash_and_status_rejected(self) -> None:
        """Wrong bytes and unresolved review cannot pass the matching declaration gate."""
        for key, value in [("audio_sha256", "0" * 64), ("status", "hold"), ("checks", {})]:
            decision = copy.deepcopy(self.decision)
            decision[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate.project_track(self.native, decision, self.tags)

    def test_required_credit_omission_rejected(self) -> None:
        """Source URLs, curators, composers and native credits cannot be silently omitted."""
        for key, value in [
            ("embedded_curators", []),
            ("embedded_source_urls", []),
            ("embedded_notices", {}),
            ("title", ""),
        ]:
            decision = copy.deepcopy(self.decision)
            decision["required_credit_fields"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate.project_track(self.native, decision, self.tags)

    def test_contact_and_unprojected_credit_rejected(self) -> None:
        """Embedded bytes with private text or unhandled supplied credit require resolution."""
        for key, value in [
            ("comment", "contact private@example.org"),
            ("publisher", "Supplied Publisher"),
        ]:
            tags = copy.deepcopy(self.tags)
            tags["format"]["tags"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate.project_track(self.native, self.decision, tags)
        tags = copy.deepcopy(self.tags)
        tags["streams"][0]["tags"]["composer"] = "Stream composer"
        with self.assertRaises(ValueError):
            candidate.project_track(self.native, self.decision, tags)

    def test_unknown_credit_key_rejected(self) -> None:
        """A reviewed dictionary still cannot introduce freeform/public contact fields."""
        self.decision["required_credit_fields"]["email"] = "private@example.org"
        with self.assertRaises(ValueError):
            candidate.project_track(self.native, self.decision, self.tags)

    def test_pinned_inventory_rejects_tampering_and_extra_files(self) -> None:
        """Fake-byte fixture tests closed inventory independently of historical audio recipes."""
        row = candidate.project_track(self.native, self.decision, self.tags)
        row["genre_ids"] = [1]
        manifest = {
            "revision": candidate.REVISION,
            "public_deployment_authorized": False,
            "rights_warranty": False,
            "source_evidence_gate": "passed_matching_declarations_and_reviewed_attribution",
            "tracks": [row],
            "audio_bytes": 4,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "audio").mkdir()
            (root / "audio/1.mp3").write_bytes(b"fake")
            (root / "index.html").write_text(candidate.PAGE)
            raw = json.dumps(manifest).encode()
            (root / "manifest.json").write_bytes(raw)
            pin = hashlib.sha256(raw).hexdigest()
            candidate.validate_candidate(root, pin)
            (root / "extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                candidate.validate_candidate(root, pin)
            (root / "extra.json").unlink()
            (root / "audio/1.mp3").write_bytes(b"evil")
            with self.assertRaises(ValueError):
                candidate.validate_candidate(root, pin)
            (root / "audio/1.mp3").write_bytes(b"fake")
            manifest["public_deployment_authorized"] = True
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                candidate.validate_candidate(root, pin)

    def test_source_null_sentinel_is_missing_credit(self) -> None:
        """Literal source null is consistently missing, never a fabricated composer."""
        self.tags["format"]["tags"]["comment"] += "\nComposer: null"
        self.tags["format"]["tags"]["publisher"] = "null"
        row = candidate.project_track(self.native, self.decision, self.tags)
        self.assertEqual(row["composer"], "")

    def test_builder_rejects_stale_tags_and_conflicting_audit(self) -> None:
        """Mock only historical validators/probe; exercise real candidate custody joins."""
        for failure in ("stale_tags", "conflict"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                site, audit = root / "site", root / "audit"
                audit.mkdir()
                native = dict(self.native, audio_path="1.mp3")
                for origin in ("original", "expanded", "coverage"):
                    base = site / origin / "audio"
                    base.mkdir(parents=True)
                    (base / "manifest.json").write_text("{}")
                    (base / "1.mp3").write_bytes(b"fake")
                comparison = {
                    "records": [
                        {
                            "track_id": 1,
                            "status": "conflict"
                            if failure == "conflict"
                            else "matching_declaration",
                            "audio_sha256": native["audio_sha256"],
                            "declared_license_url": native["license_url"],
                        }
                    ]
                }
                (audit / "embedded-license-comparison.json").write_text(json.dumps(comparison))
                (audit / "embedded-audio-tags.json").write_text(
                    json.dumps([{"track_id": 1, "tags": self.tags}])
                )
                pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in audit.iterdir()}
                decisions = {
                    "input_hashes": pins,
                    "audit_sha256": pins["embedded-license-comparison.json"],
                    "records": [self.decision],
                }
                path = root / "decisions.json"
                path.write_text(json.dumps(decisions))
                decision_pin = hashlib.sha256(path.read_bytes()).hexdigest()
                index = {
                    "tracks": {
                        "1": {
                            "artist_id": 2,
                            "title": "Example",
                            "artist_name": "Artist",
                            "genre_ids": [1],
                        }
                    },
                    "genres": [{"genre_id": 1, "title": "Genre"}],
                }
                with (
                    patch.object(candidate, "genre_index", return_value=index),
                    patch.object(
                        candidate,
                        "validate_playback_export",
                        return_value={"tracks": {"1": native}},
                    ),
                    patch.object(candidate, "_probe", return_value={}),
                    self.assertRaisesRegex(
                        ValueError, "Embedded tag evidence differs|held or misbound"
                    ),
                ):
                    candidate.build_candidate(site, audit, path, root / "output", decision_pin)

    def test_explicit_legacy_migration_preserves_bytes(self) -> None:
        """Synthetic manifest pin is patched only after production rejects it."""
        legacy = (Path(__file__).parents[1] / "fixtures/fma_candidate_legacy.html").read_bytes()
        self.assertEqual(hashlib.sha256(legacy).hexdigest(), candidate.LEGACY_PAGE_SHA256)
        row = candidate.project_track(self.native, self.decision, self.tags)
        row["genre_ids"] = [1]
        manifest = {
            "revision": candidate.REVISION,
            "public_deployment_authorized": False,
            "rights_warranty": False,
            "source_evidence_gate": "passed_matching_declarations_and_reviewed_attribution",
            "tracks": [row],
            "audio_bytes": 4,
        }
        payload = json.dumps(manifest).encode()
        pin = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "prior"
            (prior / "audio").mkdir(parents=True)
            (prior / "audio/1.mp3").write_bytes(b"fake")
            (prior / "manifest.json").write_bytes(payload)
            (prior / "index.html").write_bytes(legacy)
            with self.assertRaises(ValueError):
                candidate.validate_candidate(prior, pin)
            with self.assertRaisesRegex(ValueError, "exact reviewed"):
                candidate.rebuild_candidate(prior, root / "rejected", pin)
            with patch.object(candidate, "REVIEWED_MANIFEST_SHA256", pin):
                candidate.rebuild_candidate(prior, root / "new", pin)
            self.assertEqual((root / "new/manifest.json").read_bytes(), payload)
            self.assertEqual((root / "new/audio/1.mp3").read_bytes(), b"fake")
            self.assertEqual((prior / "index.html").read_bytes(), legacy)
            candidate.validate_candidate(root / "new", pin)
            with patch.object(candidate, "REVIEWED_MANIFEST_SHA256", pin):
                for mutation in ("page", "audio", "extra"):
                    with self.subTest(mutation=mutation):
                        (prior / "index.html").write_bytes(
                            legacy + (b"changed" if mutation == "page" else b"")
                        )
                        (prior / "audio/1.mp3").write_bytes(
                            b"evil" if mutation == "audio" else b"fake"
                        )
                        if mutation == "extra":
                            (prior / "unexpected").write_text("unexpected")
                        with self.assertRaises(ValueError):
                            candidate.rebuild_candidate(prior, root / mutation, pin)
                        self.assertFalse((root / mutation).exists())
