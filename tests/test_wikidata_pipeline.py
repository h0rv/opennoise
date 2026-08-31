import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydantic import HttpUrl

from musix.catalog.entities import EntityProjector
from musix.catalog.registry import ProjectorRegistry
from musix.models.sources import DownloadSource
from musix.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from musix.sources.registry import AdapterRegistry
from musix.sources.wikidata import WikidataSourceAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "wikidata_music_slice.json"


def _source(payload: bytes) -> DownloadSource:
    return DownloadSource(
        id="wikidata_music_fixture",
        adapter="wikidata_music_sparql_slice_v1",
        snapshot="fixture-1",
        url=HttpUrl("https://query.wikidata.org/sparql"),
        discovery_url=HttpUrl("https://www.wikidata.org/wiki/Wikidata:Data_access"),
        expected_content_type="application/sparql-results+json",
        compression="none",
        expected_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(payload).hexdigest(),
        data_license="CC0-1.0",
        license_url="https://www.wikidata.org/wiki/Wikidata:Licensing",
        rights_classification="public_domain",
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )


class WikidataPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingests_evidence_and_reuses_the_complete_attempt(self) -> None:
        payload = FIXTURE.read_bytes()
        source = _source(payload)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            object_path = vault / "raw" / "sha256" / source.checksum
            object_path.parent.mkdir(parents=True)
            object_path.write_bytes(payload)
            options = PipelineOptions(
                manifest_path=root / "manifest.toml",
                source_id=source.id,
                database_path=root / "catalog.sqlite",
                vault_path=vault,
                partition=DeterministicPartition(sha256_prefix=""),
                checkpoint_every=2,
            )
            adapters = AdapterRegistry((WikidataSourceAdapter(),))
            projectors = ProjectorRegistry((EntityProjector(),))

            summary = await run_source_pipeline(source, adapters, projectors, options)
            replay = await run_source_pipeline(source, adapters, projectors, options)

            with sqlite3.connect(options.database_path) as connection:
                counts = (
                    int(connection.execute("SELECT count(*) FROM catalog_entities").fetchone()[0]),
                    int(connection.execute("SELECT count(*) FROM entity_claims").fetchone()[0]),
                    int(
                        connection.execute("SELECT count(*) FROM artist_genre_evidence").fetchone()[
                            0
                        ]
                    ),
                    int(
                        connection.execute(
                            "SELECT count(*) FROM album_genre_membership_observations"
                        ).fetchone()[0]
                    ),
                    int(connection.execute("SELECT count(*) FROM entity_relations").fetchone()[0]),
                    int(connection.execute("SELECT count(*) FROM quarantine_events").fetchone()[0]),
                )
                named_target = connection.execute(
                    """SELECT genre.name
                       FROM genres AS genre
                       JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
                       WHERE identifier.namespace = 'wikidata'
                         AND identifier.normalized_value = 'Q500'"""
                ).fetchone()
                target_names = connection.execute(
                    """SELECT DISTINCT name_kind, name
                       FROM entity_names AS name
                       JOIN entity_identifiers AS identifier
                         ON identifier.entity_id = name.entity_id
                       WHERE identifier.namespace = 'wikidata'
                         AND identifier.normalized_value = 'Q500'
                       ORDER BY name_kind, name"""
                ).fetchall()

        self.assertEqual((summary.raw, summary.accepted, summary.quarantined), (6, 6, 0))
        self.assertTrue(replay.reused_attempt)
        self.assertEqual(counts, (7, 6, 1, 1, 1, 0))
        self.assertEqual(named_target, ("Named Target Genre",))
        self.assertEqual(
            target_names, [("alias", "Target Alias"), ("primary", "Named Target Genre")]
        )


if __name__ == "__main__":
    unittest.main()
