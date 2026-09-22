"""Boundary tests for the immutable proper-genre candidate writer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_musicbrainz_direct_genre_membership_candidate import _write_fresh_output


class DirectGenreMembershipCandidateWriterTests(unittest.TestCase):
    def test_writer_refuses_existing_file_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "candidate.json"
            _write_fresh_output(output, b"first\n")

            with self.assertRaises(FileExistsError):
                _write_fresh_output(output, b"second\n")
            self.assertEqual(output.read_bytes(), b"first\n")

            target = directory / "target.json"
            symlink = directory / "candidate-link.json"
            symlink.symlink_to(target)
            with self.assertRaises(FileExistsError):
                _write_fresh_output(symlink, b"third\n")
            self.assertTrue(symlink.is_symlink())


if __name__ == "__main__":
    unittest.main()
