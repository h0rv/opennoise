"""Build a deterministic offline feature cache from retained metadata JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from opennoise.catalog.musicbrainz_artist_names import verify_artist_name_enrichment
from opennoise.catalog.musicbrainz_candidate import verify_local_musicbrainz_candidate_catalog
from opennoise.catalog.musicbrainz_genre_labels import verify_native_musicbrainz_genre_labels
from opennoise.catalog.musicbrainz_native_artist_features import (
    iter_native_artist_feature_rows,
    verify_native_artist_features,
)
from opennoise.catalog.musicbrainz_open_features import (
    iter_open_artist_feature_rows,
    verify_open_artist_features,
)
from opennoise.catalog.musicbrainz_release_group_features import (
    iter_native_release_group_feature_rows,
    verify_native_release_group_features,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.ingest.musicbrainz.bulk_artist_tag_evidence import iter_bulk_artist_tag_rows
from opennoise.ml.microgenre_features import (
    build_artist_name_overlay,
    build_microgenre_features,
    write_feature_artifacts,
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: expected JSON object")
                rows.append(value)
    return rows


def _labels(path: Path) -> dict[str, str]:
    verified = verify_native_musicbrainz_genre_labels(directory=path.parent)
    values = verified.get("genres")
    if isinstance(values, list):
        return {
            str(row.get("musicbrainz_genre_id", row.get("id", row.get("genre_id")))): str(
                row.get("canonical_name", row.get("name", row.get("label")))
            )
            for row in values
            if isinstance(row, dict)
            and row.get("musicbrainz_genre_id", row.get("id", row.get("genre_id")))
            and row.get("canonical_name", row.get("name", row.get("label")))
        }
    raise ValueError(f"{path}: expected a label mapping or list")


def main() -> None:  # noqa: C901, PLR0912, PLR0915
    """Build and receipt the offline metadata feature candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artists", type=Path, help="additional verified artist metadata JSONL")
    parser.add_argument("--open-features-directory", type=Path, action="append")
    parser.add_argument("--native-artist-feature-directory", type=Path, action="append")
    parser.add_argument(
        "--genre-labels",
        type=Path,
        required=True,
        help="verified genre UUID to readable label JSON",
    )
    parser.add_argument("--release-records", type=Path, help="facet-scoped release metadata JSONL")
    parser.add_argument("--native-release-feature-directory", type=Path)
    parser.add_argument(
        "--bulk-artist-tag-directory",
        type=Path,
        help="verified complete UUID-projected aggregate MusicBrainz artist-tag artifact",
    )
    parser.add_argument("--direct-genre-receipt", type=Path)
    parser.add_argument("--direct-object-store", type=Path)
    parser.add_argument(
        "--artist-name-source",
        type=Path,
        help="separate verified source-bound artist name overlay JSONL",
    )
    parser.add_argument("--candidate-catalog-directory", type=Path)
    parser.add_argument("--primary-corpus-only", action="store_true")
    parser.add_argument("--artist-name-enrichment-directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rejections", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--names-output", type=Path, required=True)
    parser.add_argument("--missing-names", type=Path, required=True)
    args = parser.parse_args()
    open_feature_directories = args.open_features_directory or []
    native_artist_directories = args.native_artist_feature_directory or []
    if (
        args.artists is None
        and not open_feature_directories
        and not native_artist_directories
        and args.bulk_artist_tag_directory is None
    ):
        parser.error("supply an artist metadata input directory or --artists")
    if args.primary_corpus_only and not args.candidate_catalog_directory:
        parser.error("--primary-corpus-only requires --candidate-catalog-directory")
    if (args.direct_genre_receipt is None) != (args.direct_object_store is None):
        parser.error("--direct-genre-receipt and --direct-object-store are a pair")
    artist_rows = _jsonl(args.artists) if args.artists else []
    name_rows = list(artist_rows)
    repository_root = Path(__file__).resolve().parents[1]
    sources: dict[str, Path] = {
        "genre_labels": args.genre_labels,
        "feature_extractor_code": repository_root / "src/opennoise/ml/microgenre_features.py",
        "feature_builder_script": Path(__file__).resolve(),
    }
    open_receipts: list[dict[str, Any]] = []
    native_artist_receipts: list[dict[str, Any]] = []
    direct_receipt: DirectProperGenreCustodyReceipt | None = None
    catalog_receipt = None
    name_enrichment_receipt = None
    release_feature_receipt = None
    primary_artist_ids: set[str] | None = None
    if args.artists:
        sources["artist_metadata"] = args.artists
    for index, directory in enumerate(open_feature_directories):
        open_receipt = verify_open_artist_features(directory=directory)
        open_receipts.append(open_receipt)
        open_rows = list(iter_open_artist_feature_rows(directory=directory))
        artist_rows.extend(open_rows)
        name_rows.extend(open_rows)
        source_prefix = f"open_artist_features_{index}"
        sources[source_prefix] = directory / "artist-features.jsonl"
        sources[f"{source_prefix}_receipt"] = directory / "receipt.json"
        sources[f"{source_prefix}_manifest"] = directory / "source.json"
    for index, directory in enumerate(native_artist_directories):
        native_receipt = verify_native_artist_features(directory=directory)
        native_artist_receipts.append(native_receipt)
        native_rows = list(iter_native_artist_feature_rows(directory=directory))
        artist_rows.extend(native_rows)
        name_rows.extend(native_rows)
        source_prefix = f"native_artist_features_{index}"
        sources[source_prefix] = directory / "artist-features.jsonl"
        sources[f"{source_prefix}_receipt"] = directory / "receipt.json"
        sources[f"{source_prefix}_manifest"] = directory / "source.json"
    bulk_artist_tag_receipt: dict[str, Any] | None = None
    if args.bulk_artist_tag_directory:
        # The producer iterator validates receipt/hash/UUID partition before
        # releasing a single projected row to feature construction.
        bulk_rows = list(iter_bulk_artist_tag_rows(directory=args.bulk_artist_tag_directory))
        # Names are display metadata, not model input. Keep new core-dump names
        # out of the tag-name rejection vocabulary so adding the source cannot
        # remove previously retained musical values from other artists.
        artist_rows.extend(
            {key: value for key, value in row.items() if key != "name"} for row in bulk_rows
        )
        existing_name_ids = {
            item.get("artist_mbid")
            for item in name_rows
            if isinstance(item.get("artist_mbid"), str)
            and isinstance(
                item.get("name", item.get("artist_name", item.get("canonical_name"))), str
            )
        }
        # Core dump names are an exact-UUID fallback for unresolved display
        # names; they never replace an already verified preferred name.
        name_rows.extend(
            row
            for row in bulk_rows
            if row.get("artist_mbid") not in existing_name_ids
            and isinstance(name := row.get("name"), str)
            and name.strip()
        )
        bulk_artist_tag_receipt = json.loads(
            (args.bulk_artist_tag_directory / "receipt.json").read_text(encoding="utf-8")
        )
        source_root = args.bulk_artist_tag_directory / "source"
        if not source_root.is_dir():
            # V2 artifacts may keep retained immutable source captures beside
            # their rows; otherwise resolve the paths from the source receipt.
            source_root = (
                args.bulk_artist_tag_directory.parent
                / ("musicbrainz-bulk-artist-tags-20260930-v1")
                / "source"
            )
        core_prefix_candidates = sorted(source_root.glob("mbdump-core-prefix-*.bz2"))
        derived_archive = source_root / "mbdump-derived.tar.bz2"
        selection_path = Path(str(bulk_artist_tag_receipt.get("selection_path", "")))
        if len(core_prefix_candidates) != 1 or not derived_archive.is_file():
            raise ValueError("bulk artist-tag replay source captures are incomplete")
        if not selection_path.is_file():
            raise ValueError("bulk artist-tag UUID selection input is unavailable")
        bulk_prefix = "bulk_artist_tags_0"
        sources[bulk_prefix] = args.bulk_artist_tag_directory / "artist-tags.jsonl"
        sources[f"{bulk_prefix}_receipt"] = args.bulk_artist_tag_directory / "receipt.json"
        sources[f"{bulk_prefix}_core_prefix"] = core_prefix_candidates[0]
        sources[f"{bulk_prefix}_derived_archive"] = derived_archive
        sources[f"{bulk_prefix}_selection"] = selection_path
        if (source_root / "snapshot-index.html").is_file():
            sources[f"{bulk_prefix}_source_index"] = source_root / "snapshot-index.html"
        if (source_root / "license.html").is_file():
            sources[f"{bulk_prefix}_license"] = source_root / "license.html"
    if args.release_records:
        sources["release_records"] = args.release_records
    release_rows = _jsonl(args.release_records) if args.release_records else []
    if args.native_release_feature_directory:
        release_feature_receipt = verify_native_release_group_features(
            directory=args.native_release_feature_directory
        )
        release_rows.extend(
            iter_native_release_group_feature_rows(directory=args.native_release_feature_directory)
        )
        sources["native_release_group_features"] = (
            args.native_release_feature_directory / "release-features.jsonl"
        )
        sources["native_release_group_features_receipt"] = (
            args.native_release_feature_directory / "receipt.json"
        )
        sources["native_release_group_source_manifest"] = (
            args.native_release_feature_directory / "source.json"
        )
    proper_claims = ()
    if args.direct_genre_receipt and args.direct_object_store:
        direct_receipt = DirectProperGenreCustodyReceipt.model_validate_json(
            args.direct_genre_receipt.read_bytes()
        )
        proper_claims = iter_verified_portable_direct_proper_genre_claims(
            direct_receipt, object_store=args.direct_object_store
        )
        sources["direct_genre_receipt"] = args.direct_genre_receipt
        sources["direct_genre_claim_object"] = (
            args.direct_object_store / direct_receipt.claims_object_key
        )
    if args.artist_name_source:
        sources["artist_name_overlay"] = args.artist_name_source
        name_rows.extend(_jsonl(args.artist_name_source))
    for release in release_rows:
        artist_credit_rows = release.get("artist_credit")
        if not isinstance(artist_credit_rows, list):
            continue
        release_refs = release.get("evidence_refs", [])
        evidence_ref = (
            "|".join(value for value in release_refs if isinstance(value, str))
            if isinstance(release_refs, list)
            else str(release.get("release_group_mbid", "release-credit"))
        )
        for credit in artist_credit_rows:
            if not isinstance(credit, dict):
                continue
            artist = credit.get("artist")
            if not isinstance(artist, dict):
                continue
            artist_mbid = artist.get("id")
            display_name = credit.get("name", artist.get("name"))
            if isinstance(artist_mbid, str) and isinstance(display_name, str):
                name_rows.append(
                    {
                        "artist_mbid": artist_mbid,
                        "name": display_name,
                        "source_evidence_ref": f"release-credit:{evidence_ref}",
                    }
                )
    if args.candidate_catalog_directory:
        catalog_receipt = verify_local_musicbrainz_candidate_catalog(
            directory=args.candidate_catalog_directory
        )
        catalog_database = args.candidate_catalog_directory / "catalog.sqlite"
        with closing(sqlite3.connect(f"file:{catalog_database.resolve()}?mode=ro", uri=True)) as db:
            name_rows.extend(
                {
                    "artist_mbid": artist_mbid,
                    "canonical_name": canonical_name,
                    "source_evidence_ref": f"candidate-catalog:{catalog_receipt.database_sha256}",
                }
                for artist_mbid, canonical_name in db.execute(
                    "SELECT artist_mbid,canonical_name FROM artist WHERE canonical_name IS NOT NULL"
                )
            )
            if args.primary_corpus_only:
                primary_artist_ids = {
                    artist_mbid for (artist_mbid,) in db.execute("SELECT artist_mbid FROM artist")
                }
        sources["candidate_catalog_receipt"] = args.candidate_catalog_directory / "receipt.json"
        sources["candidate_catalog_database"] = catalog_database
    if args.artist_name_enrichment_directory:
        if not args.candidate_catalog_directory:
            parser.error(
                "--artist-name-enrichment-directory requires --candidate-catalog-directory"
            )
        name_enrichment_receipt = verify_artist_name_enrichment(
            catalog_directory=args.candidate_catalog_directory,
            directory=args.artist_name_enrichment_directory,
        )
        enriched_names = name_enrichment_receipt.get("rows")
        if not isinstance(enriched_names, list):
            raise ValueError("verified name enrichment is missing its projected rows")
        name_rows.extend(
            {
                "artist_mbid": row["artist_mbid"],
                "canonical_name": row["canonical_name"],
                "source_response_sha256": row["source_response_sha256"],
                "source_evidence_ref": f"artist-name-batch:{row['source_batch_index']}",
            }
            for row in enriched_names
            if row["canonical_name"]
        )
        sources["artist_name_enrichment_receipt"] = (
            args.artist_name_enrichment_directory / "name-enrichment.json"
        )
    rows, rejected = build_microgenre_features(
        artist_rows,
        release_records=release_rows,
        proper_genre_claims=proper_claims,
        genre_labels=_labels(args.genre_labels),
        known_artist_names=[
            name
            for item in name_rows
            if item.get("source_role") != "bulk_musicbrainz_aggregate_artist_tag"
            if isinstance(
                name := item.get("name", item.get("artist_name", item.get("canonical_name"))),
                str,
            )
        ],
    )
    if primary_artist_ids is not None:
        rows = [row for row in rows if row["artist_mbid"] in primary_artist_ids]
        rejected = [row for row in rejected if row.get("artist_mbid") in primary_artist_ids]
    receipt = write_feature_artifacts(
        rows,
        rejected,
        inputs=sources,
        output=args.output,
        rejection_output=args.rejections,
        receipt_output=args.receipt,
    )
    receipt.update(
        {
            "scope": "local_noncommercial_research",
            "public_export_authorized": False,
            "historical_assignments_read": False,
            "audio_inputs_used": False,
            "artist_identity_scope": (
                "verified_primary_candidate_catalog"
                if primary_artist_ids is not None
                else "all_verified_source_artist_identities"
            ),
        }
    )
    if open_receipts:
        receipt.update(
            {
                "open_artist_feature_output_sha256": [
                    item["output_sha256"] for item in open_receipts
                ],
                "musicbrainz_open_tags_license": "CC-BY-NC-SA-3.0",
                "musicbrainz_core_metadata_license": "CC0-1.0",
                "derived_output_obligations": (
                    "Attribution, NonCommercial, ShareAlike; local research only"
                ),
            }
        )
    if bulk_artist_tag_receipt is not None:
        receipt["bulk_artist_tag_output_sha256"] = bulk_artist_tag_receipt.get("rows_sha256")
        receipt["musicbrainz_bulk_tag_associations_license"] = "CC-BY-NC-SA-3.0"
        receipt["research_model_input_authorized"] = True
        receipt["research_model_scope"] = "local_noncommercial_research"
        receipt["musicbrainz_attribution"] = "MusicBrainz contributors; https://musicbrainz.org/"
        receipt["derived_output_obligations"] = (
            "MusicBrainz contributor attribution; noncommercial research; share alike; "
            "no public export"
        )
        receipt["public_export_authorized"] = False
        receipt["musicbrainz_bulk_artist_tag_counts"] = bulk_artist_tag_receipt.get("counts", {})
    if direct_receipt is not None:
        receipt["direct_claim_object_sha256"] = direct_receipt.claims_object_sha256
    if catalog_receipt is not None:
        receipt["candidate_catalog_output_sha256"] = catalog_receipt.output_sha256
    if native_artist_receipts:
        receipt["native_artist_feature_output_sha256"] = [
            item["output_sha256"] for item in native_artist_receipts
        ]
    if name_enrichment_receipt is not None:
        receipt["artist_name_enrichment_output_sha256"] = name_enrichment_receipt["output_sha256"]
    if release_feature_receipt is not None:
        receipt["native_release_group_feature_output_sha256"] = release_feature_receipt[
            "output_sha256"
        ]
        receipt["release_group_metadata_license"] = "CC-BY-NC-SA-3.0"
        receipt["release_features_are_credit_context"] = True
    names, missing_names = build_artist_name_overlay(
        name_rows, (row["artist_mbid"] for row in rows)
    )
    args.names_output.parent.mkdir(parents=True, exist_ok=True)
    args.missing_names.parent.mkdir(parents=True, exist_ok=True)
    args.names_output.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in names),
        encoding="utf-8",
    )
    args.missing_names.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in missing_names
        ),
        encoding="utf-8",
    )
    receipt["name_overlay_sha256"] = hashlib.sha256(args.names_output.read_bytes()).hexdigest()
    receipt["missing_names_sha256"] = hashlib.sha256(args.missing_names.read_bytes()).hexdigest()
    receipt["named_artists"] = len(names)
    receipt["missing_artist_names"] = len(missing_names)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
