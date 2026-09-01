import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from musix.ml.production_map_qa import (
    ProductionMapAcceptanceError,
    evaluate_production_map,
    require_accepted_production_map,
)
from musix.models.production_qa import (
    ProductionMapAcceptanceInput,
    ProductionMapCoordinate,
    ProductionMapInteractionEvidence,
    ProductionMapLabelBox,
    ProductionMapLod,
    ProductionMapPresentationParent,
    ProductionMapRegion,
    ProductionMapScreenshot,
    ProductionMapSimilarityEvidence,
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
    *, screenshot_directory: Path, top_10: float = 0.40, collapse: bool = False
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
            evaluated_entity_count=len(ids),
            top_10_recall=top_10,
            top_25_recall=0.31,
            prior_baseline_top_10_recall=0.52,
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
    def test_accepts_complete_noncollapsed_persistent_map_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            result = require_accepted_production_map(_input(screenshot_directory=Path(temporary)))
            self.assertTrue(result.accepted)
            self.assertEqual(result.root_region_overlap_count, 0)
            self.assertEqual(result.desktop_label_collisions[-1].overlapping_label_count, 0)

    def test_rejects_collapsed_or_low_similarity_map(self) -> None:
        with TemporaryDirectory() as temporary:
            evidence = _input(screenshot_directory=Path(temporary), top_10=0.15, collapse=True)
            result = evaluate_production_map(evidence)
            self.assertFalse(result.accepted)
            self.assertTrue(any("central p05-p95" in failure for failure in result.failures))
            self.assertTrue(any("top-10" in failure for failure in result.failures))
            with self.assertRaises(ProductionMapAcceptanceError):
                require_accepted_production_map(evidence)


if __name__ == "__main__":
    unittest.main()
