import tempfile
import unittest
from os import environ
from pathlib import Path
from typing import override
from unittest.mock import patch

from musix.app import create_app
from musix.db import Database
from musix.ml.production_map import build_production_map
from musix.ml.public_graph import build_public_model
from musix.models import MapPoint, map_view
from musix.models.modeling import PublicModelSettings
from musix.models.production import ProductionMapSettings
from tests._test_client import create_test_client
from tests.test_production_map import _inputs as production_inputs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"


class AppTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.client = create_test_client(
            create_app(
                Path(self.temporary.name) / "catalog.sqlite",
                open_construction_graph_v2_path=None,
            )
        )
        self.client.__enter__()

    @override
    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_home_is_a_minimal_full_viewport_shell(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<main id="map"', response.text)
        self.assertNotIn("<h1", response.text)
        self.assertIn("htmx-4.0.0.min.js", response.text)
        self.assertIn("/static/app.css?v=14", response.text)
        self.assertIn("cytoscape-3.34.0.min.js", response.text)
        self.assertIn("semantic-map.js?v=31", response.text)
        self.assertNotIn('id="count"', response.text)
        self.assertIn("Open 6,291", response.text)
        self.assertIn('data-map-view="open"', response.text)
        self.assertNotIn('id="map-view-switch"', response.text)
        self.assertEqual(response.text.count('id="semantic-map"'), 1)
        self.assertNotIn("data-local-research-artist-url", response.text)

    def test_local_research_panel_rejects_non_loopback_startup(self) -> None:
        with (
            patch.dict(
                environ,
                {"MUSIX_LOCAL_RESEARCH_ARTIST_EVIDENCE_ENABLED": "true", "HOST": "0.0.0.0"},  # noqa: S104
                clear=False,
            ),
            self.assertRaisesRegex(ValueError, "loopback host"),
        ):
            create_app(Path(self.temporary.name) / "other.sqlite")

    def test_open_view_uses_the_committed_artifact_in_bounded_lods(self) -> None:
        page = self.client.get("/", params={"view": "open"})
        overview = self.client.get("/api/open-construction-map", params={"level": 0})
        detail = self.client.get("/api/open-construction-map", params={"level": 3})

        self.assertEqual(page.status_code, 200)
        self.assertIn('data-map-view="open"', page.text)
        self.assertIn('data-map-mode="open"', page.text)
        self.assertIn('data-open-graph-version="v1"', page.text)
        self.assertIn('data-graph-url="/api/open-construction-map?level=0"', page.text)
        self.assertIn('data-neighbor-url="/api/open-construction-map/neighbors/"', page.text)
        self.assertNotIn('data-graph-url="/api/map"', page.text)
        for response, budget in ((overview, 240), (detail, 720)):
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["source"], "open-construction-artifact")
            self.assertEqual(payload["total_node_count"], 6291)
            self.assertEqual(payload["node_budget"], budget)
            self.assertLessEqual(len(payload["nodes"]), budget)
            self.assertLess(len(payload["nodes"]), payload["total_node_count"])
        genre_id = overview.json()["nodes"][0]["genre_id"]
        drill = self.client.get(f"/api/open-construction-map/neighbors/{genre_id}")
        invalid_level = self.client.get("/api/open-construction-map", params={"level": 4})
        partial_viewport = self.client.get("/api/open-construction-map", params={"min_x": 0})
        self.assertEqual(drill.status_code, 200)
        self.assertLessEqual(len(drill.json()["nodes"]), 25)
        self.assertLessEqual(len(drill.json()["edges"]), 24)
        self.assertEqual(invalid_level.status_code, 400)
        self.assertEqual(partial_viewport.status_code, 400)

    def test_historical_view_is_addressable_but_never_substitutes_public_data(self) -> None:
        response = self.client.get("/", params={"view": "historical"})
        api = self.client.get("/api/historical-signal-map")

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-map-view="historical"', response.text)
        self.assertIn("Historical compatibility is unavailable.", response.text)
        self.assertNotIn('data-graph-url="/api/map"', response.text)
        self.assertEqual(api.status_code, 503)

    def test_health_queries_sqlite(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "ok")

    def test_empty_map_search_and_fragment(self) -> None:
        response = self.client.get("/api/map")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("legacy-layout", response.text)
        self.assertEqual(self.client.get("/api/search", params={"q": "---"}).json(), {"hits": []})
        fragment = self.client.get("/fragments/search", params={"q": "---"})
        self.assertEqual(fragment.status_code, 200)
        self.assertEqual(fragment.text.strip(), "")

    def test_configured_production_artifact_has_stable_detail_links(self) -> None:
        inputs = production_inputs()
        source = build_public_model(inputs, PublicModelSettings())
        artifact = build_production_map(
            inputs,
            source,
            ProductionMapSettings(
                geometry_grid_size=5,
                minimum_central_span=0.05,
                minimum_occupied_cell_ratio=0.01,
                minimum_desktop_16x9_occupied_cell_ratio=0.01,
                maximum_desktop_16x9_cell_fraction=1.0,
                minimum_neighbor_preservation=0.0,
            ),
        )
        artifact_path = Path(self.temporary.name) / "production-map.json"
        artifact_path.write_text(artifact.model_dump_json(), encoding="utf-8")
        with create_test_client(
            create_app(Path(self.temporary.name) / "production.sqlite", artifact_path)
        ) as client:
            response = client.get("/api/map")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["source"], "production-artifact")
        self.assertFalse(payload["fallback"])
        self.assertEqual(len(payload["graph"]["nodes"]), len(inputs.genres))
        self.assertEqual(
            payload["detail_hrefs"]["wikidata:genre:Q1"],
            "/genres/key/wikidata%3Agenre%3AQ1",
        )

    def test_missing_or_invalid_configured_production_artifact_returns_503(self) -> None:
        missing_path = Path(self.temporary.name) / "missing-production-map.json"
        invalid_path = Path(self.temporary.name) / "invalid-production-map.json"
        invalid_path.write_text("{}", encoding="utf-8")
        for artifact_path in (missing_path, invalid_path):
            with (
                self.subTest(artifact_path=artifact_path.name),
                create_test_client(
                    create_app(Path(self.temporary.name) / "production.sqlite", artifact_path)
                ) as client,
            ):
                response = client.get("/api/map")
            self.assertEqual(response.status_code, 503)

    def test_exploration_contract_rejects_partial_viewport(self) -> None:
        empty = self.client.get("/api/explore/map")
        invalid = self.client.get("/api/explore/map", params={"min_x": "0"})
        missing = self.client.get("/api/genres/999")

        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["points"], [])
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_selection_does_not_change_source_coordinate_bounds(self) -> None:
        points = [
            MapPoint(
                entity_id=1,
                entity_kind="genre",
                name="Top",
                x=0.0,
                y=0.0,
                display_weight=None,
                color_hex=None,
            ),
            MapPoint(
                entity_id=2,
                entity_kind="genre",
                name="Bottom",
                x=100.0,
                y=1_000.0,
                display_weight=None,
                color_hex=None,
            ),
        ]

        full = map_view(points)
        selected = map_view(points, 2)

        self.assertEqual(selected.view_box, full.view_box)
        self.assertEqual(selected.view_width, full.view_width)
        self.assertEqual(selected.view_height, full.view_height)
        self.assertGreater(selected.view_height, selected.view_width)

    def test_empty_bounded_map_preserves_viewport_aspect(self) -> None:
        view = map_view([], view_box="10 20 300 700")

        self.assertEqual(view.view_box, "10 20 300 700")
        self.assertEqual(view.view_width, 300.0)
        self.assertEqual(view.view_height, 700.0)

    def test_dense_map_has_a_stable_label_budget_and_keeps_focus(self) -> None:
        points = [
            MapPoint(
                entity_id=index,
                entity_kind="genre",
                name=f"Genre {index}",
                x=float(index),
                y=float(index),
                display_weight=float(100 - index),
                color_hex=None,
            )
            for index in range(100)
        ]

        view = map_view(points, 99)

        self.assertLessEqual(len(view.label_entity_ids), 49)
        self.assertGreater(len(view.label_entity_ids), 1)
        self.assertEqual(view.label_entity_ids[0], 99)
        self.assertGreater(len(view.detail_label_entity_ids), len(view.label_entity_ids))
        self.assertIn(99, view.detail_label_entity_ids)

        shuffled = map_view(list(reversed(points)), 99)
        self.assertEqual(shuffled.label_entity_ids, view.label_entity_ids)
        self.assertEqual(shuffled.detail_label_entity_ids, view.detail_label_entity_ids)
        self.assertTrue(set(view.label_entity_ids) <= set(view.detail_label_entity_ids))


class PopulatedAppTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "catalog.sqlite"
        inputs = production_inputs()
        source = build_public_model(inputs, PublicModelSettings())
        artifact = build_production_map(
            inputs,
            source,
            ProductionMapSettings(
                geometry_grid_size=5,
                minimum_central_span=0.05,
                minimum_occupied_cell_ratio=0.01,
                minimum_desktop_16x9_occupied_cell_ratio=0.01,
                maximum_desktop_16x9_cell_fraction=1.0,
                minimum_neighbor_preservation=0.0,
            ),
        )
        production_map_path = Path(self.temporary.name) / "production-map.json"
        production_map_path.write_text(artifact.model_dump_json(), encoding="utf-8")
        database = Database(self.database_path)
        database.initialize()
        with database.connect() as connection:
            connection.executescript(FIXTURE.read_text(encoding="utf-8"))
            connection.executescript(
                """
                INSERT INTO layout_runs (
                    id, layout_key, revision, algorithm_key, algorithm_revision,
                    input_fingerprint, status, policy_id, completed_at
                ) VALUES (
                    2, 'default', 1, 'fixture', '1',
                    '3434343434343434343434343434343434343434343434343434343434343434',
                    'complete', 1, '2026-01-01T00:00:00Z'
                );
                INSERT INTO layout_points (
                    layout_run_id, entity_id, x, y, display_weight, color_hex
                ) SELECT 2, entity_id, x, y, display_weight, color_hex
                  FROM layout_points WHERE layout_run_id = 1;
                INSERT INTO current_layouts (layout_key, layout_run_id) VALUES ('default', 2);
                INSERT INTO layout_runs (
                    id, layout_key, revision, algorithm_key, algorithm_revision,
                    input_fingerprint, status, policy_id, completed_at
                ) VALUES (
                    3, 'classic', 1, 'source_coordinates', '1',
                    '4343434343434343434343434343434343434343434343434343434343434343',
                    'complete', 1, '2026-01-01T00:00:00Z'
                );
                INSERT INTO layout_points (
                    layout_run_id, entity_id, x, y, display_weight, color_hex
                ) SELECT 3, entity_id, x + 10, y + 20, display_weight, color_hex
                  FROM layout_points WHERE layout_run_id = 1;
                INSERT INTO current_layouts (layout_key, layout_run_id) VALUES ('classic', 3);
                INSERT INTO search_documents (
                    entity_id, field_kind, search_text, input_fingerprint,
                    provenance_id, policy_id
                ) VALUES (
                    1, 'primary_name', 'IDM',
                    '3535353535353535353535353535353535353535353535353535353535353535',
                    1, 1
                );
                INSERT INTO identifier_types (id, type_key, name)
                VALUES (2, 'wikidata_genre_qid', 'Wikidata Genre Qid');
                INSERT INTO entity_identifiers (
                    entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id
                ) VALUES (1, 2, 'wikidata', 'Q1', 'Q1', 1);
                INSERT INTO historical_genre_artist_observations (
                    id, genre_id, source_artist_name, observation_role, source_local_rank,
                    source_revision_date, source_artifact_sha256, provenance_id, policy_id,
                    record_fingerprint
                ) VALUES (
                    1, 1, 'Autechre', 'representative', 1, '2023-11-19',
                    '3636363636363636363636363636363636363636363636363636363636363636',
                    1, 1,
                    '3737373737373737373737373737373737373737373737373737373737373737'
                );
                INSERT INTO historical_genre_track_observations (
                    id, genre_id, artist_observation_id, source_track_title,
                    recording_provider, recording_source_id, safe_external_url,
                    legacy_preview_state, source_revision_date, source_artifact_sha256,
                    provenance_id, policy_id, record_fingerprint
                ) VALUES (
                    1, 1, 1, 'Bike', 'spotify', '0123456789012345678901',
                    'https://open.spotify.com/track/0123456789012345678901',
                    'disabled_legacy', '2023-11-19',
                    '3636363636363636363636363636363636363636363636363636363636363636',
                    1, 1,
                    '3838383838383838383838383838383838383838383838383838383838383838'
                );
                INSERT INTO provenance_records (
                    id, source_id, policy_id, snapshot_ref, artifact_sha256,
                    record_fingerprint, parser_release_ref, ingest_attempt_ref, observed_at
                ) VALUES (
                    2, 2, 2, 'private-snapshot',
                    '3939393939393939393939393939393939393939393939393939393939393939',
                    '4040404040404040404040404040404040404040404040404040404040404040',
                    'private-parser-1', 'private-attempt-1', '2026-01-02T00:00:00Z'
                );
                INSERT INTO historical_genre_artist_observations (
                    id, genre_id, source_artist_name, observation_role, source_local_rank,
                    source_revision_date, source_artifact_sha256, provenance_id, policy_id,
                    record_fingerprint
                ) VALUES (
                    2, 1, 'Hidden Artist', 'representative', 1, '2026-01-02',
                    '3939393939393939393939393939393939393939393939393939393939393939',
                    2, 2,
                    '4141414141414141414141414141414141414141414141414141414141414141'
                );
                INSERT INTO historical_genre_track_observations (
                    id, genre_id, artist_observation_id, source_track_title,
                    recording_provider, recording_source_id, safe_external_url,
                    legacy_preview_state, source_revision_date, source_artifact_sha256,
                    provenance_id, policy_id, record_fingerprint
                ) VALUES (
                    2, 1, 2, 'Hidden Track', 'spotify', '1234567890123456789012',
                    'https://open.spotify.com/track/1234567890123456789012',
                    'absent', '2026-01-02',
                    '3939393939393939393939393939393939393939393939393939393939393939',
                    2, 2,
                    '4242424242424242424242424242424242424242424242424242424242424242'
                );
                """
            )
        self.client = create_test_client(
            create_app(
                self.database_path,
                production_map_path,
                open_construction_graph_v2_path=None,
            )
        )
        self.client.__enter__()

    @override
    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_genre_links_have_one_canonical_selection_contract(self) -> None:
        response = self.client.get("/", params={"view": "public"})

        detail_href = "/genres/key/wikidata%3Agenre%3AQ1"
        self.assertIn(f'href="{detail_href}"', response.text)
        self.assertIn(f'hx-get="{detail_href}"', response.text)
        self.assertIn('hx-target="#genre-detail-slot"', response.text)
        self.assertIn(f'hx-push-url="{detail_href}"', response.text)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', response.text)
        self.assertIn('id="semantic-map"', response.text)
        self.assertIn('id="map-controls"', response.text)
        self.assertIn('aria-describedby="map-pan-help"', response.text)
        self.assertNotIn('id="layout-lenses"', response.text)
        self.assertIn('id="map-point-wikidata:genre:Q1"', response.text)
        self.assertIn("<title>Electronic music</title>", response.text)
        self.assertNotIn('id="count"', response.text)

    def test_published_layout_lenses_keep_source_and_generated_contracts_distinct(self) -> None:
        response = self.client.get("/", params={"layout": "classic", "view": "public"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('id="layout-lenses"', response.text)
        self.assertNotIn("Map layout", response.text)
        self.assertIn('id="semantic-map"', response.text)
        self.assertNotIn("<audio", response.text)
        self.assertNotIn("player", response.text.casefold())
        self.assertNotIn("preview", response.text.casefold())
        self.assertNotIn("waveform", response.text.casefold())
        self.assertNotIn(">Listen<", response.text)

    def test_unknown_layout_is_not_silently_replaced(self) -> None:
        response = self.client.get("/", params={"layout": "missing", "view": "public"})

        self.assertEqual(response.status_code, 404)

    def test_canonical_genre_url_is_a_complete_fallback(self) -> None:
        response = self.client.get("/genres/1", params={"view": "public"})

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-selected-genre="1"', response.text)
        self.assertIn('id="selection-clear"', response.text)
        self.assertIn('href="/" aria-label="Close IDM"', response.text)
        self.assertIn('id="genre-detail"', response.text)
        self.assertIn("Autechre", response.text)
        self.assertIn("Bike", response.text)
        self.assertIn(
            'href="https://open.spotify.com/track/0123456789012345678901"',
            response.text,
        )
        self.assertIn('target="_blank" rel="noreferrer"', response.text)
        self.assertNotIn("Hidden Artist", response.text)
        self.assertNotIn("Hidden Track", response.text)
        self.assertNotIn("Every Noise legacy genre map", response.text)
        self.assertNotIn("2026-01-01", response.text)

    def test_workspace_selection_and_deselection_are_atomic(self) -> None:
        selected = self.client.get("/fragments/workspace", params={"focus": "1", "view": "public"})
        reset = self.client.get("/fragments/workspace", params={"view": "public"})

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.text.count('id="workspace"'), 1)
        self.assertEqual(selected.text.count('id="search"'), 1)
        self.assertEqual(selected.text.count('id="results"'), 1)
        self.assertIn('data-selected-genre="1"', selected.text)
        self.assertIn('id="selection-clear"', selected.text)
        self.assertIn('id="genre-detail"', selected.text)
        self.assertIn("Autechre", selected.text)
        self.assertIn("Bike", selected.text)
        self.assertNotIn("Every Noise legacy genre map", selected.text)
        self.assertIn('hx-push-url="/"', selected.text)
        self.assertNotIn("600.0 800.0", selected.text)

        self.assertEqual(reset.status_code, 200)
        self.assertNotIn(" selected", reset.text)
        self.assertNotIn('id="genre-detail"', reset.text)
        self.assertNotIn('id="selection-clear"', reset.text)
        self.assertEqual(reset.text.count('id="search"'), 1)
        self.assertEqual(reset.text.count('id="results"'), 1)

    def test_search_results_are_navigable_and_share_selection_history(self) -> None:
        response = self.client.get("/fragments/search", params={"q": "idm"})

        self.assertEqual(response.status_code, 200)
        self.assertIn('<a class="result" href="/genres/1?q=idm"', response.text)
        self.assertIn('hx-get="/fragments/genres/1?q=idm"', response.text)
        self.assertIn('hx-push-url="/genres/1?q=idm"', response.text)
        self.assertNotIn("<button", response.text)

    def test_search_and_genre_entry_preserve_selected_layout(self) -> None:
        search = self.client.get("/fragments/search", params={"q": "idm", "layout": "classic"})
        selected = self.client.get(
            "/fragments/workspace", params={"focus": "1", "layout": "classic"}
        )

        self.assertIn('href="/genres/1?layout=classic&amp;q=idm"', search.text)
        self.assertIn('id="semantic-map"', selected.text)
        self.assertIn('href="/?layout=classic" aria-label="Close IDM"', selected.text)

    def test_stable_public_genre_key_has_full_and_partial_routes(self) -> None:
        encoded_key = "wikidata%3Agenre%3AQ1"

        full = self.client.get(f"/genres/key/{encoded_key}")
        partial = self.client.get(f"/genres/key/{encoded_key}", headers={"HX-Request": "true"})
        fragment = self.client.get(f"/fragments/genres/key/{encoded_key}")
        missing = self.client.get("/genres/key/wikidata%3Agenre%3AQ999999999")
        malformed = self.client.get("/genres/key/wikidata%3Aartist%3AQ9778")

        self.assertEqual(full.status_code, 200)
        self.assertIn('<main id="map"', full.text)
        self.assertIn('id="genre-detail"', full.text)
        self.assertEqual(partial.status_code, 200)
        self.assertIn('id="genre-detail"', partial.text)
        self.assertNotIn("<!doctype html>", partial.text)
        self.assertEqual(fragment.status_code, 200)
        self.assertIn('id="genre-detail"', fragment.text)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(malformed.status_code, 404)

    def test_genre_api_returns_one_historical_representative(self) -> None:
        response = self.client.get("/api/genres/1")

        self.assertEqual(response.status_code, 200)
        representative = response.json()["historical_representative"]
        self.assertEqual(representative["artist_name"], "Autechre")
        self.assertEqual(representative["track_title"], "Bike")
        self.assertEqual(representative["external_link"]["label"], "Spotify")
        self.assertEqual(response.json()["representative_album_metadata"], [])
        self.assertEqual(response.json()["neighbors"], [])


if __name__ == "__main__":
    unittest.main()
