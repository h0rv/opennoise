"""Print model-neutral metrics for a published local layout."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from musix.serving.map.layout_metrics import (
    LayoutMetricPoint,
    LayoutMetricRequest,
    RenderBudgetInput,
    VersionedPointLayout,
    evaluate_layout,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Path to a Musix SQLite database.")
    parser.add_argument("--layout", default="default", help="Published layout key to evaluate.")
    return parser.parse_args(argv)


def _load_layout(database_path: Path, layout_key: str) -> VersionedPointLayout:
    with sqlite3.connect(database_path) as connection:
        run = connection.execute(
            """SELECT run.id, run.layout_key, run.revision, run.input_fingerprint
               FROM current_layouts AS current
               JOIN layout_runs AS run ON run.id = current.layout_run_id
               WHERE current.layout_key = ?""",
            (layout_key,),
        ).fetchone()
        if run is None:
            raise ValueError(f"no published layout exists for {layout_key!r}")
        run_id, published_key, revision, input_fingerprint = run
        rows = connection.execute(
            """SELECT entity_id, x, y
               FROM layout_points
               WHERE layout_run_id = ?
               ORDER BY entity_id""",
            (run_id,),
        ).fetchall()
    return VersionedPointLayout(
        layout_key=str(published_key),
        revision=int(revision),
        input_fingerprint=str(input_fingerprint),
        points=tuple(
            LayoutMetricPoint(entity_id=int(entity_id), x=float(x), y=float(y))
            for entity_id, x, y in rows
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Load one current layout and print the metrics that need no extra evidence."""
    args = _arguments(argv)
    layout = _load_layout(args.database, args.layout)
    result = evaluate_layout(
        LayoutMetricRequest(
            layout=layout,
            render_budget=RenderBudgetInput(
                label_count=len(layout.points),
                interactive_point_count=len(layout.points),
            ),
        )
    )
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
