"""Synthetic normalized tables test provenance, denominators and container integrity."""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

from opennoise.serving.metadata import normalized_recording_dataset as dataset
from opennoise.serving.metadata.recovered_recording_catalog import page_binding, project_page
from opennoise.serving.metadata.selected_recording_catalog import canonical_json, sha256_file
from tests import test_recording_catalog_export as fixtures


class NormalizedDatasetTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        source = fixtures.CatalogExportTests().fixture(root)
        ledger = source / "request-ledger.jsonl"
        events = [json.loads(line) for line in ledger.read_bytes().splitlines()]
        for event in events:
            event["capture"]["status_code"] = 200
            event["capture"]["custody"]["complete_body"] = True
        ledger.write_bytes(b"".join(canonical_json(event) + b"\n" for event in events))
        (source / "pre-http-freeze.json").write_bytes(canonical_json({"implementation": {}}))
        (root / "scripts").mkdir()
        cli = (
            Path(dataset.__file__).resolve().parents[4]
            / "scripts/export_normalized_recording_dataset.py"
        )
        (root / "scripts/export_normalized_recording_dataset.py").write_bytes(cli.read_bytes())
        return source

    def test_joint_recording_observations_are_retained_without_global_dedup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(dataset, "verify_source", return_value={"verified": True}),
            patch.object(dataset, "_check_memory", return_value=1),
        ):
            root = Path(temporary)
            source = self.fixture(root)
            ledger_path = source / "request-ledger.jsonl"
            events = [json.loads(line) for line in ledger_path.read_bytes().splitlines()]
            first = events[0]["capture"]
            raw = zstandard.ZstdDecompressor().decompress(
                (source / first["custody"]["path"]).read_bytes()
            )
            payload = json.loads(raw)
            payload["recordings"][0]["artist-credit"].append(
                {"artist": {"id": fixtures.ZERO, "name": "Empty fixture"}}
            )
            changed = canonical_json(payload)
            (source / first["custody"]["path"]).write_bytes(
                zstandard.ZstdCompressor().compress(changed)
            )
            first["custody"]["decoded_bytes"] = len(changed)
            first["custody"]["decoded_sha256"] = hashlib.sha256(changed).hexdigest()
            first["projection"] = page_binding(project_page(changed, first["request"]))
            request = {
                "artist_mbid": fixtures.ZERO,
                "baseline_count": 1,
                "offset": 0,
                "stage": "initial",
                "url": "https://musicbrainz.org/ws/2/recording?joint-fixture",
            }
            joint_body = canonical_json(
                {
                    "recording-count": 1,
                    "recording-offset": 0,
                    "recordings": [payload["recordings"][0]],
                }
            )
            (source / "custody/joint.zst").write_bytes(
                zstandard.ZstdCompressor().compress(joint_body)
            )
            events.append(
                {
                    "event": "outcome",
                    "sequence": 6,
                    "capture": {
                        "request": request,
                        "outcome": "native_core_page",
                        "status_code": 200,
                        "fetched_at": first["fetched_at"],
                        "custody": {
                            "path": "custody/joint.zst",
                            "complete_body": True,
                            "decoded_bytes": len(joint_body),
                            "decoded_sha256": hashlib.sha256(joint_body).hexdigest(),
                        },
                        "projection": page_binding(project_page(joint_body, request)),
                    },
                }
            )
            ledger_path.write_bytes(b"".join(canonical_json(event) + b"\n" for event in events))
            summaries = json.loads((source / "artists.json").read_bytes())
            for field in [
                "returned_nonprobe_rows",
                "baseline_advertised_count",
                "unique_exact_credited_recordings",
            ]:
                summaries[1][field] = 1
            (source / "artists.json").write_bytes(canonical_json(summaries))
            output = root / "joint"
            dataset.export_dataset(source, root, output)
            self.assertEqual(dataset.replay_dataset(source, root, output)["rows"], 502)
            controls = json.loads((output / "dataset.json").read_bytes())
            self.assertIsNone(controls["counts"]["global_unique_recordings"])

    def reseal(self, output: Path) -> None:
        receipt = json.loads((output / "receipt.json").read_bytes())
        for name in receipt["files"]:
            digest, count = sha256_file(output / name)
            receipt["files"][name] = {"sha256": digest, "bytes": count}
        (output / "receipt.json").write_bytes(canonical_json(receipt))

    def test_deterministic_stream_and_complete_zero_artist_controls(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(dataset, "verify_source", return_value={"verified": True}),
            patch.object(dataset, "_check_memory", return_value=1),
        ):
            root = Path(temporary)
            source = self.fixture(root)
            first, second = root / "first", root / "second"
            self.assertEqual(dataset.export_dataset(source, root, first)["rows"], 501)
            dataset.export_dataset(source, root, second)
            for filename in ["observations.jsonl.gz", "captures.jsonl.gz"]:
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            controls = json.loads((first / "dataset.json").read_bytes())
            self.assertEqual(len(controls["artists"]), 2)
            self.assertEqual(controls["artists"][1]["returned_nonprobe_rows"], 0)
            self.assertIsNone(controls["counts"]["global_unique_recordings"])
            self.assertTrue(dataset.replay_dataset(source, root, first)["verified"])
            with self.assertRaises(FileExistsError):
                dataset.export_dataset(source, root, first)

    def test_rehashed_native_row_capture_count_scope_and_container_mutations(self) -> None:  # noqa: C901, PLR0912, PLR0915 - explicit adversarial cases.
        for case in [
            "row",
            "capture",
            "count",
            "scope",
            "mtime",
            "trailing",
            "decoded_hash",
            "empty_member",
            "padding",
            "recipe",
            "cli",
            "code",
        ]:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as temporary,
                patch.object(dataset, "verify_source", return_value={"verified": True}),
                patch.object(dataset, "_check_memory", return_value=1),
            ):
                root = Path(temporary)
                source = self.fixture(root)
                output = root / "dataset"
                dataset.export_dataset(source, root, output)
                if case in {"row", "capture", "trailing"}:
                    name = "captures.jsonl.gz" if case == "capture" else "observations.jsonl.gz"
                    rows = [
                        json.loads(line)
                        for line in gzip.decompress((output / name).read_bytes()).splitlines()
                    ]
                    if case == "row":
                        rows[0]["credited_artist_mbids"] = []
                    elif case == "capture":
                        rows[0]["decoded_sha256"] = "0" * 64
                    else:
                        rows.append(rows[-1])
                    raw = b"".join(canonical_json(row) + b"\n" for row in rows)
                    with (
                        (output / name).open("wb") as stream,
                        gzip.GzipFile(
                            filename="", mode="wb", fileobj=stream, mtime=0, compresslevel=6
                        ) as compressed,
                    ):
                        compressed.write(raw)
                elif case in {"count", "scope"}:
                    path = output / "dataset.json"
                    value = json.loads(path.read_bytes())
                    if case == "count":
                        value["counts"]["global_unique_recordings"] = 501
                    else:
                        value["policy"]["representative_judgments"] = 1
                    path.write_bytes(canonical_json(value))
                elif case == "mtime":
                    path = output / "observations.jsonl.gz"
                    raw = bytearray(path.read_bytes())
                    raw[4] = 1
                    path.write_bytes(raw)
                elif case in {"empty_member", "padding"}:
                    path = output / "observations.jsonl.gz"
                    with path.open("ab") as stream:
                        stream.write(
                            gzip.compress(b"", mtime=0) if case == "empty_member" else b"\0"
                        )
                elif case in {"recipe", "cli", "code"}:
                    path = output / "construction.json"
                    value = json.loads(path.read_bytes())
                    if case == "recipe":
                        value["recipe"]["cli_argv"].append("--skip-native-proof")
                    elif case == "cli":
                        value["invocation_kind"] = "cli"
                        value["actual_cli_argv"] = ["unrecorded"]
                    else:
                        value["implementation"].pop(next(iter(value["implementation"])))
                    path.write_bytes(canonical_json(value))
                else:
                    path = output / "receipt.json"
                    value = json.loads(path.read_bytes())
                    value["tables"]["observations.jsonl.gz"]["decoded_sha256"] = "0" * 64
                    path.write_bytes(canonical_json(value))
                self.reseal(output)
                with self.assertRaises(ValueError):
                    dataset.replay_dataset(source, root, output)

    def test_encoded_budget_and_extra_alias_are_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(dataset, "verify_source", return_value={"verified": True}),
            patch.object(dataset, "_check_memory", return_value=1),
        ):
            root = Path(temporary)
            source = self.fixture(root)
            with patch.object(dataset, "MAX_ENCODED_BYTES", 1), self.assertRaises(ValueError):
                dataset.export_dataset(source, root, root / "refused")
            output = root / "valid"
            dataset.export_dataset(source, root, output)
            (output / "unexpected.json").symlink_to(source / "selection.json")
            with self.assertRaises(ValueError):
                dataset.replay_dataset(source, root, output)

        for destination in ["source_child", "source_alias", "ancestor_alias"]:
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.fixture(root)
                before = {
                    path.relative_to(source).as_posix(): sha256_file(path)
                    for path in source.rglob("*")
                    if path.is_file()
                }
                target = source / "new-dataset"
                if destination == "source_alias":
                    target = root / "source-alias"
                    target.symlink_to(source, target_is_directory=True)
                elif destination == "ancestor_alias":
                    alias = root / "directory-alias"
                    alias.symlink_to(root, target_is_directory=True)
                    target = alias / "new-dataset"
                with (
                    patch.object(dataset, "verify_source") as native,
                    self.assertRaises(ValueError),
                ):
                    dataset.export_dataset(source, root, target)
                native.assert_not_called()
                self.assertEqual(
                    before,
                    {
                        path.relative_to(source).as_posix(): sha256_file(path)
                        for path in source.rglob("*")
                        if path.is_file()
                    },
                )


if __name__ == "__main__":
    unittest.main()
