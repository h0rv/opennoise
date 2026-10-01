"""Fit selected source associations and export bounded local artist proposal shards."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import (
    MAX_BATCH,
    EnrichmentModel,
    EnrichmentSettings,
    fit_enrichment,
    load_enrichment,
    read_profiles,
    save_enrichment,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import BinaryIO

PREFIX_COUNT = 256
DEFAULT_PROPOSALS = 3


def _write_batch(  # noqa: PLR0913 - explicit bounded model/profile/output batch boundary.
    model: EnrichmentModel,
    rows: Sequence[Mapping[str, object]],
    profiles: Mapping[str, tuple[str, ...]],
    streams: Mapping[str, BinaryIO],
    counts: Counter[str],
    *,
    limit: int,
) -> None:
    proposals = model.proposal_batch(rows, limit=limit)
    for row in rows:
        artist = str(row["artist_mbid"])
        prefix = artist[:2]
        if re.fullmatch(r"[0-9a-f]{2}", prefix) is None:
            raise ValueError("artist proposal shard requires a canonical hexadecimal ID prefix")
        values = profiles[artist]
        features = proposals[artist]
        state = (
            "proposals" if features else "no_supported_proposals" if values else "no_observed_music"
        )
        counts[state] += 1
        counts["artist_count"] += 1
        counts["proposal_count"] += len(features)
        payload = {
            "artist_mbid": artist,
            "feature_proposals": features,
            "observed_music_values": values,
            "state": state,
        }
        streams[prefix].write(canonical_json(payload) + b"\n")


def export_proposals(
    *, features: Path, selection: Path, output: Path, limit: int = DEFAULT_PROPOSALS
) -> dict[str, object]:
    """Fit latest source profiles using frozen inner-selected settings, with no new test claim."""
    require_local_candidate_destination(output)
    if output.exists():
        raise FileExistsError("refusing to replace source feature proposal export")
    selected = TypeAdapter(dict[str, object]).validate_json(selection.read_bytes())
    settings = TypeAdapter(EnrichmentSettings).validate_python(selected["settings"])
    training_hash = sha256_file(features)[0]
    profiles, proper = read_profiles(features)
    model = fit_enrichment(profiles, proper, settings=settings, training_sha256=training_hash)
    output.mkdir(parents=True)
    model_receipt = save_enrichment(model, output / "model")
    model = load_enrichment(output / "model")
    journals = output / "proposal-journals"
    journals.mkdir()
    counts: Counter[str] = Counter()
    with ExitStack() as stack:
        streams = {
            f"{i:02x}": stack.enter_context((journals / f"{i:02x}.jsonl").open("xb"))
            for i in range(PREFIX_COUNT)
        }
        rows: list[dict[str, object]] = []
        with features.open(encoding="utf-8") as stream:
            for line in stream:
                rows.append(TypeAdapter(dict[str, object]).validate_json(line))
                if len(rows) == MAX_BATCH:
                    _write_batch(model, rows, profiles, streams, counts, limit=limit)
                    rows.clear()
            if rows:
                _write_batch(model, rows, profiles, streams, counts, limit=limit)
    shards = output / "feature-proposals"
    shards.mkdir()
    for journal in sorted(journals.iterdir()):
        artists = {}
        with journal.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                artist = row.pop("artist_mbid")
                if artist in artists:
                    raise ValueError("proposal shard repeats an artist")
                artists[artist] = row
        (shards / f"{journal.stem}.json").write_bytes(canonical_json({"artists": artists}) + b"\n")
        journal.unlink()
    journals.rmdir()
    if counts["artist_count"] != len(profiles) or sha256_file(features)[0] != training_hash:
        raise ValueError("source changed or artist export coverage differs")
    frozen_builder = output / "exporter.py"
    frozen_builder.write_bytes(Path(__file__).read_bytes())
    receipt: dict[str, object] = {
        "revision": "source-artist-feature-proposal-export-v1",
        "scope": "local_research_only",
        "public_export_authorized": False,
        "role": "inferred_feature_proposals",
        "native_fact": False,
        "scores_calibrated": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "training_sha256": training_hash,
        "training_input_sha256": training_hash,
        "model_sha256": model.model_sha256,
        "model_receipt_sha256": sha256_file(output / "model/receipt.json")[0],
        "model_output_sha256": model_receipt["output_sha256"],
        "selection_artifact_sha256": sha256_file(selection)[0],
        "settings": asdict(settings),
        "selection_role": "inner_validation_on_previously_explored_rich_v2_corpus",
        "latest_full_fit_has_new_test_claim": False,
        "cold_profiles_abstain": True,
        "proposal_limit": limit,
        "shard_count": PREFIX_COUNT,
        "counts": dict(counts),
        "code_bindings": model_receipt["implementation_bindings"],
        "exporter_sha256": sha256_file(frozen_builder)[0],
        "files": {
            str(path.relative_to(output)): {
                "sha256": sha256_file(path)[0],
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / "prediction-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def main() -> None:
    """Require the source features and a frozen inner-validation selection artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=DEFAULT_PROPOSALS)
    args = parser.parse_args()
    receipt = export_proposals(
        features=args.features, selection=args.selection, output=args.output, limit=args.limit
    )
    print(json.dumps(receipt["counts"], indent=2))  # noqa: T201 - local research diagnostics.


if __name__ == "__main__":
    main()
