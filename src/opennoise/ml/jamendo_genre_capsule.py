# ruff: noqa: PLR2004 -- fixed retained cohort/model census.
"""Export only frozen outer weights and exact native context, without fitting."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from opennoise.ml import jamendo_genre_inference as pure

METADATA_BYTES = 1_611_903
INPUT_BYTES = 2_000_000
NATIVE_SHA256 = "9848cd3a855e8b40018c50e949d3d38b6aad533c2323f8d68a7419cd5a5002e9"
OLD_CODE = {
    "jamendo_human_genre.py": ("9f4663644a941f64a78359d2677cc07cadce5b0719f756defc2d26be15869b5d"),
    "jamendo_human_mood.py": NATIVE_SHA256,
    "run_jamendo_human_genre.py": (
        "0cb4c6401387e2ee42355699c7646e4618bd63df60026630ea85ad558d2af35e"
    ),
}
STUDY_CODE = {
    "jamendo_genre_temperature.py": (
        "a32873379b4b2de8bc2e4a082ce781aa2d2424041059bd38adc0fc5a6e1dd882"
    ),
    "run_jamendo_genre_temperature.py": (
        "d886f1d398876084807d150bd476076732c512b40caf6742fdf7c5df6c325477"
    ),
}


def selected_models(
    path: Path, receipt_path: Path, receipt_pin: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Accept an honest external study envelope for the one exact frozen model payload."""
    receipt = pure.read(receipt_path, INPUT_BYTES, receipt_pin)
    if (
        not isinstance(receipt, dict)
        or receipt.get("revision") != "jamendo-temperature-result-v1"
        or receipt.get("research_only") is not True
        or any(receipt.get(k) != v for k, v in pure.RIGHTS.items())
    ):
        raise ValueError("Trusted study receipt revision or rights differs")
    runtime = receipt["runtime"]
    original = runtime["original"]
    numerical = pure.runtime()
    if (
        runtime["code"] != STUDY_CODE
        or original["code"] != OLD_CODE
        or any(original[k] != numerical[k] for k in ("python", "numpy", "scipy"))
        or receipt["inputs"]["protocol"] != pure.SOURCE["temperature_protocol_sha256"]
    ):
        raise ValueError("Trusted study runtime or protocol differs")
    if (
        not isinstance(receipt["inputs"], dict)
        or set(receipt["inputs"]) != {"protocol", "identity_seal", "census_seal", "result_receipt"}
        or any(
            not isinstance(v, str) or not pure.HASH.fullmatch(v) for v in receipt["inputs"].values()
        )
        or not isinstance(receipt["inner_census_sha256"], str)
        or not pure.HASH.fullmatch(receipt["inner_census_sha256"])
    ):
        raise ValueError("Trusted study input pins differ")
    files = receipt["files"]
    if (
        not isinstance(files, dict)
        or set(files) != {"models.json", "predictions.json", "evaluation.json"}
        or files["models.json"]
        != {"bytes": path.stat().st_size, "sha256": pure.SOURCE["selected_models_sha256"]}
    ):
        raise ValueError("Trusted selected-model binding differs")
    return pure.read(path, INPUT_BYTES, pure.SOURCE["selected_models_sha256"]), receipt


def build(  # noqa: PLR0913, PLR0917 - explicit original artifacts and external custody pins.
    metadata: Path,
    outer_models: Path,
    selected: Path,
    study_receipt: Path,
    study_pin: str,
    protocol: Path,
    protocol_pin: str,
    output: Path,
) -> str:
    """Project pinned metadata/weights only; never open original targets or saved predictions."""
    inputs = (metadata, outer_models, selected, study_receipt, protocol)
    pure.fresh(output, inputs)
    if protocol_pin != pure.CONTRACT:
        raise ValueError("Frozen capsule contract differs")
    pure.read(protocol, INPUT_BYTES, pure.CONTRACT)
    pure.safe(metadata)
    if (
        not metadata.is_file()
        or metadata.stat().st_size != METADATA_BYTES
        or pure.sha(metadata) != pure.SOURCE["metadata_sha256"]
    ):
        raise ValueError("Exact metadata source bytes required")
    outer = pure.read(outer_models, INPUT_BYTES, pure.SOURCE["outer_models_sha256"])
    selections, receipt = selected_models(selected, study_receipt, study_pin)
    from opennoise.ml import jamendo_human_mood as native  # noqa: PLC0415

    if pure.sha(Path(native.__file__)) != NATIVE_SHA256:
        raise ValueError("Native identity parser differs")
    observations = native.parse(metadata, human=False, identity_only=True)
    groups = native.components(observations)
    by_id = {r.track_id: r for r in observations}
    context = sorted(
        {
            (r.artist_id, r.album_id, groups[r.track_id], pure.fold(groups[r.track_id]))
            for r in observations
        }
    )
    routing = {"pairs": [list(r) for r in context]}
    artists, albums, pairs = pure.routing(routing)
    counts = {
        "artists": len(artists),
        "albums": len(albums),
        "pairs": len(pairs),
        "components": len({c for c, _ in artists.values()}),
    }
    if (
        len(observations) != 11565
        or counts != {"artists": 713, "albums": 2365, "pairs": 2365, "components": 713}
        or len(outer) != 5
        or len(selections) != 5
    ):
        raise ValueError("Complete retained source/model census differs")
    frames = []
    for i, (old, choice) in enumerate(zip(outer, selections, strict=True)):
        if (
            old["fold"] != i
            or choice["outer"] != i
            or len(set(old["training_track_ids"])) != len(old["training_track_ids"])
            or any(t not in by_id or pure.fold(groups[t]) == i for t in old["training_track_ids"])
            or old["training_components"] != sorted({groups[t] for t in old["training_track_ids"]})
            or any(pure.fold(c) == i for c in old["training_components"])
        ):
            raise ValueError("Original native outer training isolation differs")
        frames.append(
            {
                "fold": i,
                "model": old["model"],
                "model_reason": old["reason"],
                "temperature": choice["temperature"],
                "temperature_reason": choice["reason"],
            }
        )
    models = {
        "classes": list(pure.CLASSES),
        "mapping": [list(t) for t in pure.MAPPING],
        "folds": frames,
    }
    pure.validate_models(models)
    data = {"models.json": pure.encoded(models), "routing.json": pure.encoded(routing)}
    manifest = {
        "revision": pure.REVISION,
        "contract_sha256": pure.CONTRACT,
        "source": {
            **pure.SOURCE,
            "study_receipt_sha256": study_pin,
            "study_inputs": receipt["inputs"],
            "inner_census_sha256": receipt["inner_census_sha256"],
        },
        "runtime": pure.runtime(),
        "builder": {
            Path(__file__).name: pure.sha(Path(__file__)),
            Path(native.__file__).name: NATIVE_SHA256,
        },
        "rights": pure.RIGHTS,
        "counts": counts,
        "files": {
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for name, raw in data.items()
        },
    }
    data["manifest.json"] = pure.encoded(manifest)
    if sum(map(len, data.values())) > pure.CAPSULE_BYTES:
        raise ValueError("Capsule byte cap exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".genre-capsule-", dir=output.parent) as temporary:
        stage = Path(temporary) / "capsule"
        stage.mkdir()
        for name, raw in data.items():
            (stage / name).write_bytes(raw)
        pin = pure.sha(stage / "manifest.json")
        pure.load(stage, pin)
        stage.rename(output)
    return pin
