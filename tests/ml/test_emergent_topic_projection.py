"""Immutable model receipt projection checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.emergent_topic_projection import seal_topic_projection


class TopicProjectionTests(unittest.TestCase):
    def _source(self, source: Path, *, role: str = "inferred_community_membership") -> None:
        source.mkdir()
        (source / "communities.json").write_bytes(
            canonical_json({"communities": [{"role": "inferred_music_community"}]})
        )
        (source / "assignments.jsonl").write_bytes(
            canonical_json({"artist_mbid": "source-id", "memberships": [{"role": role}]}) + b"\n"
        )
        (source / "primary-assignments.json").write_text("{}")
        report = {
            "scope": "local_research_only",
            "historical_inputs_used": False,
            "artist_names_used_for_construction": False,
            "public_export_authorized": False,
            "files": {
                path.name: {"sha256": sha256_file(path)[0], "bytes": path.stat().st_size}
                for path in source.iterdir()
            },
        }
        report["output_sha256"] = sha256_json(report)
        (source / "report.json").write_bytes(canonical_json(report))

    def test_projection_preserves_frozen_source_bytes_and_seals_explicit_zero(self) -> None:
        with TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            self._source(source)
            original = (source / "report.json").read_bytes()
            report = seal_topic_projection(source, output)
            self.assertEqual(report["native_genre_memberships_added"], 0)
            self.assertEqual(report["verified_inferred_membership_count"], 1)
            self.assertEqual(original, (source / "report.json").read_bytes())
            self.assertEqual(
                (source / "assignments.jsonl").read_bytes(),
                (output / "assignments.jsonl").read_bytes(),
            )
            self.assertEqual(report["source_report_sha256"], sha256_file(source / "report.json")[0])
            sealed = json.loads((output / "report.json").read_bytes())
            identity = sealed.pop("output_sha256")
            self.assertEqual(identity, sha256_json(sealed))
            with self.assertRaises(FileExistsError):
                seal_topic_projection(source, output)

    def test_noninferred_membership_cannot_be_redeclared_as_zero_native_mutations(self) -> None:
        with TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            self._source(source, role="native_observation")
            with self.assertRaisesRegex(ValueError, "native membership role"):
                seal_topic_projection(source, output)
            self.assertFalse(output.exists())

    def test_changed_artifact_cannot_receive_a_projection_receipt(self) -> None:
        with TemporaryDirectory(dir=Path.cwd() / ".cache") as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            self._source(source)
            (source / "assignments.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "byte binding"):
                seal_topic_projection(source, output)
            self.assertFalse(output.exists())
