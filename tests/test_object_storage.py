import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.storage import LocalObjectStore, ObjectConflictError, ObjectKey


class ObjectKeyTests(unittest.TestCase):
    def test_accepts_a_normal_relative_key(self) -> None:
        key = ObjectKey(value="raw/wikidata/abc123")

        self.assertEqual(key.parts, ("raw", "wikidata", "abc123"))

    def test_rejects_traversal_absolute_and_platform_paths(self) -> None:
        for value in ("../secret", "/absolute", "raw//object", "raw\\object", "raw/object/"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ObjectKey(value=value)


class LocalObjectStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_push_is_immutable_and_exact_replays_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"a" * (2 * 1024 * 1024 + 17))
            store = LocalObjectStore(root / "store")
            key = ObjectKey(value="raw/sha256/example")

            first = await store.push(source, key)
            replay = await store.push(source, key)

            self.assertFalse(first.reused)
            self.assertTrue(replay.reused)
            self.assertEqual(first.sha256, replay.sha256)
            self.assertEqual(first.byte_size, 2 * 1024 * 1024 + 17)
            self.assertTrue(await store.exists(key))

    async def test_push_rejects_different_content_for_an_existing_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"first")
            store = LocalObjectStore(root / "store")
            key = ObjectKey(value="raw/fixed")
            await store.push(source, key)
            source.write_bytes(b"second")

            with self.assertRaises(ObjectConflictError):
                await store.push(source, key)

    async def test_pull_atomically_replaces_the_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"verified artifact")
            store = LocalObjectStore(root / "store")
            key = ObjectKey(value="snapshots/source/artifact")
            pushed = await store.push(source, key)
            destination = root / "output" / "artifact.bin"
            destination.parent.mkdir()
            destination.write_bytes(b"old")

            pulled = await store.pull(key, destination)

            self.assertEqual(destination.read_bytes(), b"verified artifact")
            self.assertEqual(pulled.sha256, pushed.sha256)
            self.assertEqual(pulled.byte_size, pushed.byte_size)

    async def test_symlink_cannot_escape_the_store_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store_root = root / "store"
            outside = root / "outside"
            outside.mkdir()
            store = LocalObjectStore(store_root)
            (store_root / "escape").symlink_to(outside, target_is_directory=True)
            source = root / "source.bin"
            source.write_bytes(b"data")

            with self.assertRaisesRegex(RuntimeError, "outside the store root"):
                await store.push(source, ObjectKey(value="escape/object"))
            self.assertFalse((outside / "object").exists())


if __name__ == "__main__":
    unittest.main()
