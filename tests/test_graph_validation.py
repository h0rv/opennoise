import unittest

from pydantic import ValidationError

from opennoise.ml.validation import build_graph_validation
from opennoise.models.catalog import ArtistCoListenRunProjection
from opennoise.models.modeling import (
    ArtistPairEvidence,
    DirectMembershipEvidence,
    GenreIdentity,
    PublicArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from opennoise.models.validation import (
    GenreHierarchyEdge,
    GraphValidationInput,
    GraphValidationSettings,
    TemporalPairWindow,
)

_SHA_WD = "a" * 64
_WINDOW_SECONDS = 86_400


def _pair(left: str, right: str, day: int) -> ArtistPairEvidence:
    return ArtistPairEvidence(
        left_artist_id=left,
        right_artist_id=right,
        listener_day_support=day + 5,
        supporting_windows=1,
        evidence_refs=(f"lb:{day}:{left}:{right}",),
    )


def _window(day: int) -> TemporalPairWindow:
    start = day * _WINDOW_SECONDS
    return TemporalPairWindow(
        window_start=start,
        window_end=start + _WINDOW_SECONDS,
        pairs=(
            _pair("artist:a", "artist:e", day),
            _pair("artist:b", "artist:e", day),
            _pair("artist:c", "artist:f", day),
            _pair("artist:d", "artist:f", day),
        ),
    )


def _artifacts() -> tuple[PublicArtifact, ...]:
    return tuple(
        PublicArtifact(
            source="listenbrainz",
            snapshot=f"{2_600 + day}-202608{24 + day:02d}-000003-incremental",
            artifact_key=f"listenbrainz:{day:064x}",
            content_sha256=f"{day:064x}",
            export_allowed=True,
        )
        for day in range(1, 8)
    )


def _run() -> ArtistCoListenRunProjection:
    return ArtistCoListenRunProjection(
        external_id="joint-corpus",
        adapter_key="listenbrainz_incremental_listens_v1",
        adapter_version="1.0.0",
        adapter_build_sha256="b" * 64,
        aggregation_version="fixed-window-distinct-users-v1",
        configuration_sha256="c" * 64,
        window_seconds=_WINDOW_SECONDS,
        minimum_distinct_users=5,
        listens_seen=700,
        listens_with_artist_mbid=600,
        distinct_artists=6,
        user_windows=100,
        candidate_pairs=40,
        emitted_pairs=28,
        quarantined_records=0,
        minimum_listened_at=0,
        maximum_listened_at=7 * _WINDOW_SECONDS - 1,
        elapsed_ms=50,
        peak_rss_bytes=1_000_000,
    )


def _base_input() -> PublicModelInput:
    genres = tuple(
        GenreIdentity(
            genre_id=f"wikidata:genre:Q{index}",
            name=f"Genre {index}",
            evidence_refs=(f"wd:Q{index}",),
        )
        for index in range(1, 5)
    )
    memberships = tuple(
        DirectMembershipEvidence(
            artist_id=f"artist:{artist}",
            genre_id=f"wikidata:genre:Q{genre}",
            facet="wikidata_p136",
            value=1.0,
            evidence_ref=f"wd:{artist}:Q{genre}",
        )
        for artist, genre in (
            ("a", 1),
            ("b", 1),
            ("a", 2),
            ("b", 2),
            ("c", 3),
            ("d", 3),
            ("c", 4),
            ("d", 4),
        )
    )
    return PublicModelInput(
        artifacts=(
            PublicArtifact(
                source="wikidata",
                snapshot="wd-2026-08-31",
                artifact_key="wikidata:music-slice",
                content_sha256=_SHA_WD,
                export_allowed=True,
            ),
        ),
        genres=genres,
        direct_memberships=memberships,
    )


def _validation_input() -> GraphValidationInput:
    return GraphValidationInput(
        base_inputs=_base_input(),
        source_artifacts=_artifacts(),
        event_windows=tuple(_window(day) for day in range(7)),
        corpus_run=_run(),
        hierarchy=(
            GenreHierarchyEdge(
                child_genre_id="wikidata:genre:Q2",
                parent_genre_id="wikidata:genre:Q1",
                evidence_ref="wd:Q2:P279:Q1",
            ),
        ),
        input_database_bytes=12_345,
        input_artifact_bytes=54_321,
    )


class GraphValidationTests(unittest.TestCase):
    def test_builds_deterministic_event_time_and_hierarchy_report(self) -> None:
        inputs = _validation_input()
        model_settings = PublicModelSettings(neighbors_per_genre=3)
        validation_settings = GraphValidationSettings(neighbors_per_genre=2)

        first = build_graph_validation(inputs, model_settings, validation_settings)
        second = build_graph_validation(inputs, model_settings, validation_settings)
        changed_resources = inputs.model_copy(
            update={
                "corpus_run": inputs.corpus_run.model_copy(
                    update={"elapsed_ms": 999, "peak_rss_bytes": 999}
                )
            }
        )
        resource_repeat = build_graph_validation(
            changed_resources, model_settings, validation_settings
        )

        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.input_sha256, resource_repeat.input_sha256)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.output_sha256, resource_repeat.output_sha256)
        self.assertTrue(first.deterministic_rerun)
        self.assertTrue(first.export_allowed)
        self.assertEqual(len(first.source_artifacts), 7)
        self.assertEqual(first.event_windows, 7)
        self.assertEqual(first.hierarchy_edges, 1)
        self.assertEqual(len(first.temporal), 2)
        self.assertEqual(first.source_holdout.status, "unavailable")
        self.assertEqual(first.neighborhood.genres_evaluated, 4)
        self.assertEqual(first.neighborhood.mean_knn_preservation, 1.0)
        self.assertEqual(first.resources.input_database_bytes, 12_345)
        self.assertEqual(first.resources.input_artifact_bytes, 54_321)
        self.assertEqual(first.community_stability.experiment_count, 3)

    def test_rejects_noncontiguous_windows_duplicate_artifacts_and_low_privacy(self) -> None:
        valid = _validation_input()
        gap = valid.event_windows[1].model_copy(
            update={
                "window_start": valid.event_windows[1].window_start + 1,
                "window_end": valid.event_windows[1].window_end + 1,
            }
        )
        with self.assertRaisesRegex(ValidationError, "contiguous"):
            GraphValidationInput(
                base_inputs=valid.base_inputs,
                source_artifacts=valid.source_artifacts,
                event_windows=(valid.event_windows[0], gap, *valid.event_windows[2:]),
                corpus_run=valid.corpus_run,
                hierarchy=(),
                input_database_bytes=1,
                input_artifact_bytes=1,
            )
        with self.assertRaisesRegex(ValidationError, "unique"):
            GraphValidationInput(
                base_inputs=valid.base_inputs,
                source_artifacts=(*valid.source_artifacts[:-1], valid.source_artifacts[0]),
                event_windows=valid.event_windows,
                corpus_run=valid.corpus_run,
                hierarchy=(),
                input_database_bytes=1,
                input_artifact_bytes=1,
            )
        with self.assertRaisesRegex(ValidationError, "privacy floor"):
            GraphValidationInput(
                base_inputs=valid.base_inputs,
                source_artifacts=valid.source_artifacts,
                event_windows=valid.event_windows,
                corpus_run=valid.corpus_run.model_copy(update={"minimum_distinct_users": 2}),
                hierarchy=(),
                input_database_bytes=1,
                input_artifact_bytes=1,
            )

    def test_rejects_graphs_above_quadratic_validation_cap(self) -> None:
        with self.assertRaisesRegex(ValueError, "quadratic-work"):
            build_graph_validation(
                _validation_input(),
                PublicModelSettings(neighbors_per_genre=3),
                GraphValidationSettings(neighbors_per_genre=2, maximum_validation_genres=3),
            )


if __name__ == "__main__":
    unittest.main()
