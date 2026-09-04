import unittest
from pathlib import Path

from musix.historical_signal_store import HistoricalSignalMapStore, HistoricalSignalMapStoreError
from musix.models.historical_signal import (
    HistoricalSignalArtifact,
    HistoricalSignalLOD,
    HistoricalSignalNeighbor,
    HistoricalSignalNode,
    HistoricalSignalPublicationArtifact,
    HistoricalSignalPublicationQuality,
    HistoricalSignalTile,
)


def _node(index: int, lod_min: int) -> HistoricalSignalNode:
    return HistoricalSignalNode(
        genre_id=f"genre:{index:04d}",
        name=f"Genre {index:04d}",
        x=1.0,
        y=0.5,
        community_id="overview:00",
        component_id=0,
        membership_count=1,
        lod_min=lod_min,
        evidence_kind="h3_genre_to_artist",
    )


def _artifact() -> HistoricalSignalPublicationArtifact:
    overview = tuple(_node(index, 0) for index in range(24))
    detailed = tuple(_node(index, 3) for index in range(24, 2_001))
    nodes = overview + detailed
    tile = HistoricalSignalTile(
        level=3,
        column=0,
        row=0,
        node_ids=tuple(node.genre_id for node in detailed[:512]),
    )
    # model_construct is deliberate: the store boundary is tested independently
    # of the 6,291-node publication validator.
    signal_map = HistoricalSignalArtifact.model_construct(
        nodes=nodes,
        progressive_lods=tuple(
            HistoricalSignalLOD(level=level, node_count=count, focus_edge_budget=20)
            for level, count in enumerate((24, 24, 24, 2_001))
        ),
        tiles=(tile,),
        neighbors=(
            HistoricalSignalNeighbor(
                genre_id="genre:0000",
                neighbor_genre_id="genre:0001",
                rank=1,
                weighted_jaccard=0.5,
                cosine=0.5,
                idf_overlap=1.0,
                shared_artist_count=1,
            ),
        ),
    )
    return HistoricalSignalPublicationArtifact.model_construct(
        revision="historical-signal-publication-v1",
        source_signal_artifact_sha256="a" * 64,
        h2_artifact_sha256="b" * 64,
        h3_artifact_sha256="c" * 64,
        map=signal_map,
        quality=HistoricalSignalPublicationQuality.model_construct(node_count=len(nodes)),
    )


class HistoricalSignalMapStoreTests(unittest.TestCase):
    def _store(self) -> HistoricalSignalMapStore:
        store = HistoricalSignalMapStore(Path("configured.json"))
        store._artifact = _artifact()  # noqa: SLF001 - inject a validated-store fixture.
        store._loaded = True  # noqa: SLF001 - do not read a file in the response-slice test.
        artifact = store._artifact  # noqa: SLF001 - complete the in-memory fixture indexes.
        if artifact is None:
            self.fail("store fixture must have an artifact")
        store._node_by_id = {node.genre_id: node for node in artifact.map.nodes}  # noqa: SLF001
        store._nodes_by_level = tuple(  # noqa: SLF001
            tuple(node for node in artifact.map.nodes if node.lod_min <= level)
            for level in range(4)
        )
        store._tiles_by_key = {  # noqa: SLF001
            (tile.level, tile.column, tile.row): tile for tile in artifact.map.tiles
        }
        store._neighbors_by_genre = {  # noqa: SLF001
            "genre:0000": (artifact.map.neighbors[0],),
        }
        return store

    def test_overview_is_24_nodes_and_has_zero_initial_edges(self) -> None:
        response = self._store().response(level=0)
        self.assertIsNotNone(response)
        if response is not None:
            self.assertEqual(len(response.nodes), 24)
            self.assertEqual(response.initial_edge_count, 0)

    def test_close_lod_requires_tile_when_it_exceeds_cap(self) -> None:
        with self.assertRaisesRegex(HistoricalSignalMapStoreError, "response cap"):
            self._store().response(level=3)

    def test_tile_and_neighbors_are_independently_bounded(self) -> None:
        store = self._store()
        tile = store.response(level=3, column=0, row=0)
        neighbors = store.neighbors("genre:0000")
        self.assertIsNotNone(tile)
        self.assertIsNotNone(neighbors)
        if tile is not None:
            self.assertEqual(len(tile.nodes), 512)
        if neighbors is not None:
            self.assertEqual(len(neighbors.neighbors), 1)


if __name__ == "__main__":
    unittest.main()
