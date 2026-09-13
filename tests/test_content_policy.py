import io
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

from pydantic import HttpUrl, ValidationError

from opennoise.models.sources import DownloadSource
from opennoise.policy import AudioContentRejectedError, require_metadata_prefix
from opennoise.sources.musicbrainz import AdapterLimits, iter_artist_archive
from opennoise.storage import LocalObjectStore, ObjectKey

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DEPENDENCIES = frozenset(
    {"audioread", "ffmpeg-python", "librosa", "mutagen", "pydub", "soundfile", "torchaudio"}
)


def _source(*, url: str, content_type: str) -> DownloadSource:
    return DownloadSource(
        id="metadata_fixture",
        adapter="fixture_v1",
        snapshot="1",
        url=HttpUrl(url),
        discovery_url=HttpUrl("https://example.test/"),
        expected_content_type=content_type,
        compression="none",
        expected_bytes=1,
        checksum_algorithm="sha256",
        checksum="0" * 64,
        data_license="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )


class ContentPolicyTests(unittest.TestCase):
    def test_manifest_rejects_media_urls_types_and_non_metadata_kind(self) -> None:
        with self.assertRaises((AudioContentRejectedError, ValidationError)):
            _source(url="https://example.test/sample.mp3", content_type="application/octet-stream")
        with self.assertRaises((AudioContentRejectedError, ValidationError)):
            _source(url="https://example.test/metadata", content_type="audio/mpeg")
        source = _source(
            url="https://example.test/metadata.json",
            content_type="application/json",
        )
        source_data = source.model_dump()
        source_data["content_kind"] = "audio"
        with self.assertRaises(ValidationError):
            DownloadSource.model_validate(source_data)

    def test_common_audio_signatures_are_rejected(self) -> None:
        for prefix in (
            b"ID3metadata",
            b"fLaCmetadata",
            b"OggSmetadata",
            b"RIFF\x00\x00\x00\x00WAVE",
            b"\x00\x00\x00\x18ftypM4A ",
            b"\xff\xfb\x90d",
        ):
            with self.subTest(prefix=prefix), self.assertRaises(AudioContentRejectedError):
                require_metadata_prefix(prefix)

    def test_object_store_rejects_media_paths_and_disguised_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LocalObjectStore(root / "store")
            named_audio = root / "sample.mp3"
            named_audio.write_bytes(b"not even audio")
            disguised = root / "metadata.bin"
            disguised.write_bytes(b"ID3audio")

            with self.assertRaises(AudioContentRejectedError):
                store.push(named_audio, ObjectKey(value="raw/named"))
            with self.assertRaises(AudioContentRejectedError):
                store.push(disguised, ObjectKey(value="raw/disguised"))

    def test_archive_adapter_rejects_audio_members_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "artist.tar.xz"
            with tarfile.open(archive_path, "w:xz") as archive:
                payload = b"ID3audio"
                member = tarfile.TarInfo("previews/sample.mp3")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

            with self.assertRaises(AudioContentRejectedError):
                list(iter_artist_archive(archive_path, AdapterLimits()))

    def test_project_declares_no_audio_processing_dependency(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {
            item.split("[", maxsplit=1)[0].split("=", maxsplit=1)[0].split(">", maxsplit=1)[0]
            for item in project["project"]["dependencies"]
        }
        self.assertTrue(FORBIDDEN_DEPENDENCIES.isdisjoint(declared))


if __name__ == "__main__":
    unittest.main()
