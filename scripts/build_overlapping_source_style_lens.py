"""Retain an optional local rare-oriented inference lens after frozen confirmation."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file
from opennoise.ml.artist_feature_enrichment import MAX_BATCH
from opennoise.ml.artist_style_associations import (
    StyleProfiles,
    duplicate_signature,
    read_style_profiles,
)
from opennoise.ml.overlapping_source_styles import fit_overlapping_styles


def build(  # noqa: C901 - one immutable fit and receipt boundary.
    source: Path, confirmation: Path, output: Path
) -> dict[str, object]:
    """Fit the frozen 0.35 candidate, gated on repeated rare recovery, without export."""
    report = json.loads(confirmation.read_text())
    candidate = report["metrics"]["overlap_0.35"]
    baseline = report["metrics"]["enrichment_4"]
    if (
        candidate["rare_artist_tag_only"]["recall_at_10"]
        <= baseline["rare_artist_tag_only"]["recall_at_10"]
    ):
        raise ValueError("confirmation did not repeat rare recovery improvement")
    declaration = json.loads((confirmation.parent / "declaration.json").read_text())
    if not declaration["confirmation_disjoint_from_exploratory_targets"]:
        raise ValueError("full fit requires disjoint confirmation")
    if sha256_file(source)[0] != declaration["source_sha256"]:
        raise ValueError("full source differs from confirmation")
    require_local_candidate_destination(output)
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    frozen = output / "frozen-code"
    frozen.mkdir()
    for relative in (
        "scripts/build_overlapping_source_style_lens.py",
        "src/opennoise/ml/overlapping_source_styles.py",
        "src/opennoise/ml/artist_style_associations.py",
        "src/opennoise/ml/artist_feature_enrichment.py",
        "src/opennoise/ml/emergent_topics.py",
        "src/opennoise/analysis/emergent_topic_holdout.py",
    ):
        path = project / relative
        (frozen / path.name).write_bytes(path.read_bytes())
    profiles = read_style_profiles(source)

    def canonical(mapping: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        return {
            artist: tuple(sorted({duplicate_signature(value) for value in values}))
            for artist, values in mapping.items()
        }

    authority = {}
    for artist, values in profiles.authority.items():
        authority[artist] = {}
        for value, weight in values.items():
            signature = duplicate_signature(value)
            authority[artist][signature] = max(authority[artist].get(signature, 0), weight)
    full = StyleProfiles(
        canonical(profiles.music),
        canonical(profiles.artist_music),
        canonical(profiles.artist_tags),
        canonical(profiles.proper),
        authority,
        profiles.input_sha256,
    )
    labels: dict[str, str] = {}
    with source.open() as stream:
        for line in stream:
            for feature in json.loads(line)["features"]:
                if (value := musical_value(feature)) is not None:
                    signature = duplicate_signature(value)
                    labels[signature] = min(labels.get(signature, value), value)
    model = fit_overlapping_styles(full, rarity_power=0.35)
    sparse.save_npz(output / "associations.npz", model.associations)
    (output / "vocabulary.json").write_bytes(
        canonical_json({"values": model.vocabulary, "display_labels": labels}) + b"\n"
    )
    artists = tuple(sorted(full.music))
    covered = proposals = 0
    with (
        output.joinpath("inferred-proposals.jsonl.gz").open("xb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream,
    ):
        for start in range(0, len(artists), MAX_BATCH):
            ranked = model.rank_batch(full, artists[start : start + MAX_BATCH])
            for artist, values in ranked.items():
                covered += bool(values)
                proposals += len(values)
                stream.write(
                    canonical_json({"artist_mbid": artist, "inferred_source_values": values})
                    + b"\n"
                )
    receipt = {
        "scope": "local_research_optional_rare_oriented_lens",
        "public_export_authorized": False,
        "default_model_replaced": False,
        "source_sha256": sha256_file(source)[0],
        "confirmation_report_sha256": sha256_file(confirmation)[0],
        "rarity_power": 0.35,
        "artist_count": len(artists),
        "covered_artists": covered,
        "inferred_proposals": proposals,
        "source_value_vocabulary": len(model.vocabulary),
        "active_overlapping_neighborhoods": int(sum(model.associations.getnnz(axis=1) > 0)),
        "associations": model.associations.nnz,
        "independent_listening_relevance_proven": False,
        "proposal_role": "uncalibrated_inferred_source_value_not_artist_fact_or_genre_identity",
        "source_custody": "MusicBrainz local research; retain attribution/share-alike obligations",
        "files": {
            str(path.relative_to(output)): sha256_file(path)[0]
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
        "implementation": {
            str(path): sha256_file(path)[0]
            for path in (Path(__file__), Path("src/opennoise/ml/overlapping_source_styles.py"))
        },
    }
    (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def main() -> None:
    """Build only the explicit optional research output from a confirmation report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--confirmation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.features, args.confirmation, args.output), indent=2))  # noqa: T201 - CLI output.


if __name__ == "__main__":
    main()
