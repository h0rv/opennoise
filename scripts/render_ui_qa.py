"""Render deterministic UI fixtures and enforce small accessibility budgets."""

import argparse
import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import override

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field

from musix.layouts import DerivedCoordinateSpace, PublishedLayout
from musix.models import FrozenModel, MapPoint, map_view

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "musix" / "templates"
CSS = ROOT / "src" / "musix" / "static" / "app.css"
MAX_HTML_BYTES = 512 * 1024
MAX_CSS_BYTES = 16 * 1024
MAX_ELEMENTS = 4_000
MAX_FOCUSABLE = 1_000
FORBIDDEN_ELEMENTS = frozenset({"audio", "canvas", "iframe", "video"})


class UiInspection(FrozenModel):
    """Record deterministic structural and size checks for one fixture."""

    html_bytes: int = Field(ge=0, le=MAX_HTML_BYTES)
    css_bytes: int = Field(ge=0, le=MAX_CSS_BYTES)
    element_count: int = Field(ge=0, le=MAX_ELEMENTS)
    focusable_count: int = Field(ge=0, le=MAX_FOCUSABLE)
    landmark_ids: tuple[str, ...]


class ScreenshotResult(FrozenModel):
    """Identify one generated screenshot without treating it as source data."""

    name: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    path: str
    byte_size: int = Field(gt=0)


class UiQaReport(FrozenModel):
    """Describe one complete local UI fixture check."""

    inspection: UiInspection
    chromium: str
    screenshots: tuple[ScreenshotResult, ...]


class _Inspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.element_count = 0
        self.focusable_count = 0
        self.ids: list[str] = []
        self.forbidden: set[str] = set()
        self.main_count = 0
        self.search_count = 0
        self.named_svg_count = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.element_count += 1
        values = dict(attrs)
        if tag in FORBIDDEN_ELEMENTS:
            self.forbidden.add(tag)
        if element_id := values.get("id"):
            self.ids.append(element_id)
        if tag == "main":
            self.main_count += 1
        if values.get("role") == "search":
            self.search_count += 1
        if tag == "svg" and values.get("role") == "group" and values.get("aria-label"):
            self.named_svg_count += 1
        if tag in {"a", "button", "input", "select", "textarea"} or "tabindex" in values:
            self.focusable_count += 1


def fixture_html(*, zoom_id: str = "zoom-default") -> str:
    """Render one dense four-lens workspace for repeatable UI checks."""
    layouts = tuple(
        PublishedLayout(
            layout_key=key,
            point_count=100,
            coordinate_space=DerivedCoordinateSpace(units="layout_units"),
        )
        for key in ("public", "public-direct", "public-community", "public-taxonomy")
    )
    named_points = [
        ("An exceptionally long right edge genre name", 1_000.0, 360.0),
        ("Dense neighboring genre alpha", 105.0, 104.0),
        ("Dense neighboring genre beta", 109.0, 108.0),
        ("Distant genre", 30.0, 920.0),
    ]
    generated_points = [
        (f"Genre {index:03d}", 90.0 + (index % 18) * 18.0, 80.0 + (index // 18) * 20.0)
        for index in range(5, 101)
    ]
    points = [
        MapPoint(
            entity_id=index,
            entity_kind="genre",
            name=name,
            x=x,
            y=y,
            display_weight=float(101 - index),
            color_hex=None,
        )
        for index, (name, x, y) in enumerate(
            (*named_points, *generated_points),
            start=1,
        )
    ]
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(enabled_extensions=("html",)),
    )
    rendered = environment.get_template("index.html").render(
        active_layout=layouts[0],
        genre=None,
        hits=(),
        layout_key="public",
        layouts=layouts,
        map=map_view(points),
        search_query="",
    )
    stylesheet = CSS.resolve().as_uri()
    rendered = rendered.replace("/static/app.css?v=7", stylesheet)
    if zoom_id != "zoom-default":
        rendered = rendered.replace(
            'id="zoom-default" name="map-zoom" type="radio" checked',
            'id="zoom-default" name="map-zoom" type="radio"',
        ).replace(
            f'id="{zoom_id}" name="map-zoom" type="radio"',
            f'id="{zoom_id}" name="map-zoom" type="radio" checked',
        )
    return rendered.replace('<script src="/static/htmx-4.0.0.min.js" defer></script>', "")


def inspect_fixture(html: str) -> UiInspection:
    """Fail closed on duplicate landmarks, unnamed SVG, media, and size regressions."""
    parser = _Inspector()
    parser.feed(html)
    duplicate_ids = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate element IDs: {', '.join(duplicate_ids)}")
    if parser.forbidden:
        raise ValueError(f"forbidden UI elements: {', '.join(sorted(parser.forbidden))}")
    if parser.main_count != 1 or parser.search_count != 1 or parser.named_svg_count != 1:
        raise ValueError("fixture requires one main, search landmark, and named SVG")
    required_ids = (
        "workspace",
        "layout-lenses",
        "map-zoom",
        "map",
        "map-canvas",
        "plot",
        "search",
        "query",
        "results",
    )
    missing = tuple(element_id for element_id in required_ids if element_id not in parser.ids)
    if missing:
        raise ValueError(f"fixture is missing required IDs: {', '.join(missing)}")
    return UiInspection(
        html_bytes=len(html.encode()),
        css_bytes=CSS.stat().st_size,
        element_count=parser.element_count,
        focusable_count=parser.focusable_count,
        landmark_ids=required_ids,
    )


def _screenshot(
    chromium: str, html_path: Path, output: Path, width: int, height: int
) -> ScreenshotResult:
    subprocess.run(  # noqa: S603
        [
            chromium,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            "--run-all-compositor-stages-before-draw",
            "--force-device-scale-factor=1",
            f"--window-size={width},{height}",
            f"--screenshot={output}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    return ScreenshotResult(
        name=output.stem,
        width=width,
        height=height,
        path=str(output),
        byte_size=output.stat().st_size,
    )


def render(output: Path, chromium: str | None = None) -> UiQaReport:
    """Write a fixed HTML fixture, screenshots, and a machine-readable report."""
    browser = chromium or shutil.which("chromium")
    if browser is None:
        raise RuntimeError("Chromium is required for screenshot QA")
    output.mkdir(parents=True, exist_ok=True)
    html = fixture_html()
    inspection = inspect_fixture(html)
    html_path = output / "workspace.html"
    html_path.write_text(html, encoding="utf-8")
    detail_html_path = output / "workspace-detail.html"
    detail_html_path.write_text(fixture_html(zoom_id="zoom-detail"), encoding="utf-8")
    screenshots = (
        _screenshot(browser, html_path, output / "desktop-100.png", 1440, 900),
        _screenshot(browser, detail_html_path, output / "desktop-200.png", 1440, 900),
        _screenshot(browser, html_path, output / "mobile-100.png", 390, 844),
        _screenshot(browser, detail_html_path, output / "mobile-200.png", 390, 844),
    )
    report = UiQaReport(inspection=inspection, chromium=browser, screenshots=screenshots)
    (output / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    """Render the UI QA bundle from command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-qa"))
    parser.add_argument("--chromium")
    arguments = parser.parse_args()
    sys.stdout.write(render(arguments.output, arguments.chromium).model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
