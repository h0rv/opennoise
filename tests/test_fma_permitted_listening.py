"""Bound audio decompression, native file custody and exact per-track export behavior."""

from __future__ import annotations

import bz2
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.serving.metadata import fma_listening


class FMAListeningTests(unittest.TestCase):
    """Audio stays bounded and explicitly licensed with user-initiated controls."""

    def test_bzip_member_bomb_is_bounded(self) -> None:
        """A source member cannot exceed the numeric acquisition limit during decompression."""
        compressed = bz2.compress(b"A" * (fma_listening.MAX_RANGE + 1))
        with self.assertRaisesRegex(ValueError, "exceeds bound"):
            fma_listening.decode_audio(compressed, fma_listening.ZIP_BZIP2)

    def test_native_file_hash_size_and_symlink_are_checked(self) -> None:
        """Changing or redirecting a captured member cannot preserve its custody."""
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            body = b"native excerpt"
            (directory / "audio.range").write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            self.assertEqual(
                fma_listening.bound_file(directory, "audio.range", sha, len(body)), body
            )
            with self.assertRaisesRegex(ValueError, "hash differs"):
                fma_listening.bound_file(directory, "audio.range", "0" * 64, len(body))
            with self.assertRaisesRegex(ValueError, "exceeds bound or differs"):
                fma_listening.bound_file(directory, "audio.range", sha, len(body) + 1)
            (directory / "link.range").symlink_to(directory / "audio.range")
            with self.assertRaisesRegex(ValueError, "symlink differs"):
                fma_listening.bound_file(directory, "link.range", sha, len(body))
            with self.assertRaisesRegex(ValueError, "path or symlink differs"):
                fma_listening.bound_file(directory, "../audio.range", sha, len(body))

    def test_export_escapes_source_text_and_preserves_license(self) -> None:
        """Literal source text is safe; audio has controls without autoplay or eager fetch."""
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source = directory / "source"
            source.mkdir()
            body = b"native audio bytes"
            (source / "1.mp3").write_bytes(body)
            track = {
                "track_id": "1",
                "track_title": "<script>bad</script>",
                "artist_name": "A & B",
                "audio_path": "1.mp3",
                "audio_sha256": hashlib.sha256(body).hexdigest(),
                "audio_bytes": len(body),
                "attribution": "A & B — source",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "license_title": "CC BY 4.0",
                "track_url": "https://freemusicarchive.org/music/example/",
                "track_copyright_c": "",
                "track_copyright_p": "",
            }
            projection = {"tracks": [track]}
            (source / "listening.json").write_text(json.dumps(projection))
            output = directory / "export"
            with patch.object(fma_listening, "verify_fma_listening_pack", return_value=projection):
                manifest = fma_listening.export_fma_listening(source, source, output)
            html = (output / "index.html").read_text()
            self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
            self.assertIn('preload="none"', html)
            self.assertIn('data-track-id="1"', html)
            self.assertIn("CC BY 4.0", html)
            self.assertNotIn("autoplay", html)
            self.assertEqual(manifest["files"]["1.mp3"]["sha256"], track["audio_sha256"])
            self.assertEqual((output / "1.mp3").read_bytes(), body)
