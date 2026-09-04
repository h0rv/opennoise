import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import ValidationError

from musix.ml.production_map_qa import (
    ProductionMapAcceptanceError,
    evaluate_production_map,
    require_accepted_production_map,
)
from musix.models.production_qa import (
    ProductionMapAcceptanceInput,
    ProductionMapCoordinate,
    ProductionMapEligibleSet,
    ProductionMapInteractionEvidence,
    ProductionMapLabelBox,
    ProductionMapLod,
    ProductionMapPresentationParent,
    ProductionMapRegion,
    ProductionMapScreenshot,
    ProductionMapSimilarityEvidence,
    hash_eligible_sets,
)


def _boxes(ids: tuple[str, ...], *, mobile: bool) -> tuple[ProductionMapLabelBox, ...]:
    width = 390 if mobile else 1366
    columns = 5 if mobile else 6
    return tuple(
        ProductionMapLabelBox(
            entity_id=entity_id,
            min_x=10.0 + (index % columns) * ((width - 50) / columns),
            min_y=10.0 + (index // columns) * 90.0,
            max_x=40.0 + (index % columns) * ((width - 50) / columns),
            max_y=26.0 + (index // columns) * 90.0,
        )
        for index, entity_id in enumerate(ids)
    )


def _screenshot(
    viewport: Literal["desktop", "mobile"],
    color_scheme: Literal["light", "dark", "system"],
    width: int,
    height: int,
    directory: Path,
) -> ProductionMapScreenshot:
    path = directory / f"{viewport}-{color_scheme}.png"
    payload = f"{viewport}-{color_scheme}".encode()
    path.write_bytes(payload)
    return ProductionMapScreenshot(
        viewport=viewport,
        color_scheme=color_scheme,
        width=width,
        height=height,
        path=str(path),
        sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
    )


def _input(
    *,
    screenshot_directory: Path,
    top_10: float = 0.55,
    canonical_baseline_top_10: float = 0.55,
    collapse: bool = False,
) -> ProductionMapAcceptanceInput:
    ids = tuple(f"genre:{index:02d}" for index in range(30))
    coordinates = tuple(
        ProductionMapCoordinate(
            entity_id=entity_id,
            x=0.50 if collapse else 0.05 + (index % 6) * 0.18,
            y=0.50 if collapse else 0.05 + (index // 6) * 0.225,
        )
        for index, entity_id in enumerate(ids)
    )
    screenshots = tuple(
        _screenshot(viewport, scheme, width, height, screenshot_directory)
        for viewport, width, height in (("desktop", 1366, 768), ("mobile", 390, 844))
        for scheme in ("light", "dark", "system")
    )
    eligible_sets = tuple(
        ProductionMapEligibleSet(
            query_entity_id=entity_id,
            eligible_candidate_count=len(ids) - 1,
            reference_neighbor_count=10,
            eligible_candidate_ids_sha256=sha256(f"eligible:{entity_id}".encode()).hexdigest(),
        )
        for entity_id in ids
    )
    eligible_sets_digest = hash_eligible_sets(eligible_sets)
    return ProductionMapAcceptanceInput(
        revision="production-map-v1",
        coordinate_sha256="d" * 64,
        coordinates=coordinates,
        taxonomy_edges=tuple((entity_id, ids[0]) for entity_id in ids[1:]),
        presentation_parents=tuple(
            ProductionMapPresentationParent(
                child_id=entity_id,
                parent_id=None if index == 0 else ids[0],
                relation="none" if index == 0 else "taxonomy",
                reason="root" if index == 0 else "source taxonomy",
            )
            for index, entity_id in enumerate(ids)
        ),
        regions=(
            ProductionMapRegion(
                region_id=ids[0],
                entity_ids=ids,
                min_x=0.0,
                min_y=0.0,
                max_x=1.0,
                max_y=1.0,
                is_root=True,
            ),
        ),
        lods=tuple(
            ProductionMapLod(
                level=level,
                visible_entity_ids=ids[:count],
                desktop_labels=_boxes(ids[:count], mobile=False),
                mobile_labels=_boxes(ids[:count], mobile=True),
            )
            for level, count in enumerate((5, 15, 30))
        ),
        similarity=ProductionMapSimilarityEvidence(
            source_model_sha256="e" * 64,
            source_neighbor_sha256="f" * 64,
            candidate_coordinate_sha256="d" * 64,
            canonical_baseline_model_sha256="e" * 64,
            canonical_baseline_neighbor_sha256="f" * 64,
            canonical_baseline_coordinate_sha256="a" * 64,
            eligibility_rule_version="qa-eligible-mapped-v1",
            eligible_sets_sha256=eligible_sets_digest,
            canonical_baseline_eligibility_rule_version="qa-eligible-mapped-v1",
            canonical_baseline_eligible_sets_sha256=eligible_sets_digest,
            evaluated_entity_count=30,
            eligible_sets=eligible_sets,
            top_10_recall=top_10,
            top_25_recall=0.31,
            canonical_baseline_top_10_recall=canonical_baseline_top_10,
            random_top_10_recall=10 / 29,
        ),
        screenshots=screenshots,
        interactions=ProductionMapInteractionEvidence(
            drag_pan=True,
            touch_pan=True,
            wheel_zoom=True,
            pinch_zoom=True,
            click_opens_detail=True,
            search_preserves_map_state=True,
            browser_back_restores_map_state=True,
            no_javascript_svg_fallback=True,
            keyboard_focus_visible=True,
            dark_mode_toggle=True,
        ),
    )


class ProductionMapQaTests(unittest.TestCase):
    def test_global_spring_baseline_passes_complete_production_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            result = require_accepted_production_map(_input(screenshot_directory=Path(temporary)))
            self.assertTrue(result.accepted)
            self.assertEqual(result.root_region_overlap_count, 0)
            self.assertEqual(result.desktop_label_collisions[-1].overlapping_label_count, 0)
            self.assertGreaterEqual(result.normalized_top_10_quality, 0.98)

    def test_local_force_layout_fails_calibrated_similarity_gate(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = _input(
                screenshot_directory=Path(temporary),
                top_10=0.40,
                canonical_baseline_top_10=0.55,
                collapse=True,
            )
            result = evaluate_production_map(evidence)
            self.assertFalse(result.accepted)
            self.assertTrue(any("central p05-p95" in failure for failure in result.failures))
            self.assertTrue(any("normalized quality" in failure for failure in result.failures))
            self.assertTrue(any("exact random null" in failure for failure in result.failures))
            with self.assertRaises(ProductionMapAcceptanceError):
                require_accepted_production_map(evidence)

    def test_uses_exact_variable_eligible_set_random_null(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = _input(screenshot_directory=Path(temporary))
            variable_sets = tuple(
                ProductionMapEligibleSet(
                    query_entity_id=f"genre:{index:02d}",
                    eligible_candidate_count=29 if index % 2 == 0 else 18,
                    reference_neighbor_count=10 if index % 2 == 0 else 7,
                    eligible_candidate_ids_sha256=sha256(f"variable:{index}".encode()).hexdigest(),
                )
                for index in range(30)
            )
            exact_random = sum(
                min(10, entry.reference_neighbor_count) / entry.eligible_candidate_count
                for entry in variable_sets
            ) / len(variable_sets)
            similarity = ProductionMapSimilarityEvidence.model_validate(
                {
                    **evidence.similarity.model_dump(mode="python"),
                    "eligible_sets": variable_sets,
                    "eligible_sets_sha256": hash_eligible_sets(variable_sets),
                    "canonical_baseline_eligible_sets_sha256": hash_eligible_sets(variable_sets),
                    "random_top_10_recall": exact_random,
                }
            )
            self.assertEqual(similarity.random_top_10_recall, exact_random)
            with self.assertRaisesRegex(ValidationError, "exact eligible-neighbor null"):
                ProductionMapSimilarityEvidence.model_validate(
                    {
                        **similarity.model_dump(mode="python"),
                        "random_top_10_recall": exact_random + 0.001,
                    }
                )

    def test_rejects_mismatched_model_neighbor_and_eligibility_hashes(self) -> None:
        with TemporaryDirectory() as temporary:
            similarity = _input(screenshot_directory=Path(temporary)).similarity
            cases = (
                ("canonical_baseline_model_sha256", "a" * 64, "same source model hash"),
                ("canonical_baseline_neighbor_sha256", "b" * 64, "same neighbor hash"),
                (
                    "canonical_baseline_eligible_sets_sha256",
                    "c" * 64,
                    "same eligible-set hash",
                ),
            )
            for field, replacement, message in cases:
                with self.subTest(field=field), self.assertRaisesRegex(ValidationError, message):
                    ProductionMapSimilarityEvidence.model_validate(
                        {**similarity.model_dump(mode="python"), field: replacement}
                    )

    def test_rejects_similarity_evidence_for_a_different_coordinate_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = _input(screenshot_directory=Path(temporary))
            with self.assertRaisesRegex(ValidationError, "candidate coordinate artifact"):
                ProductionMapAcceptanceInput.model_validate(
                    {
                        **evidence.model_dump(mode="python"),
                        "similarity": {
                            **evidence.similarity.model_dump(mode="python"),
                            "candidate_coordinate_sha256": "a" * 64,
                        },
                    }
                )


if __name__ == "__main__":
    unittest.main()
