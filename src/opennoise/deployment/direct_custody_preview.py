"""Create a static, local-only explorer of source-bound neighborhood candidates."""

from __future__ import annotations

import itertools
import json
import math
import shutil
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, TypeAdapter

from opennoise.catalog.musicbrainz_artist_names import verify_artist_name_enrichment
from opennoise.catalog.musicbrainz_candidate import (
    require_local_candidate_destination,
    verify_local_musicbrainz_candidate_catalog,
)
from opennoise.catalog.musicbrainz_genre_labels import verify_native_musicbrainz_genre_labels
from opennoise.catalog.musicbrainz_release_context import write_artist_release_contexts
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.direct_artist_shards import (
    join_artist_map_labels,
    write_direct_artist_shards,
    write_genre_detail_shards,
)
from opennoise.ml.direct_custody_artist_maps import build_genre_artist_maps
from opennoise.ml.direct_custody_neighborhoods import load_neighborhood_index
from opennoise.ml.direct_custody_reconstruction import load_reconstruction, verify_artist_proposal
from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, build_rectangular_atlas
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from opennoise.ml.direct_custody_neighborhoods import ObservationIndex

EXAMPLE_LIMIT = 20
_STATIC = Path(__file__).resolve().parents[1] / "static"
_REVISION = "direct-custody-static-local-preview-v1"


class ModelPeer(FrozenModel):
    """An explicitly inferred genre neighbor, never a source claim."""

    seed_id: str
    score: float = Field(gt=0, allow_inf_nan=False)
    shared_artist_count: int = Field(ge=2)
    role: Literal["inferred_genre_overlap_neighbor"]


class ArtistProposal(FrozenModel):
    """A review-only proposal with its direct source genre explanations."""

    artist_mbid: str
    score: float = Field(gt=0, allow_inf_nan=False)
    role: Literal["inferred_artist_candidate"]
    via_seed_ids: tuple[str, ...]
    opposing_seed_ids: tuple[str, ...] = ()


class ModelGenre(FrozenModel):
    """Bounded source count and separately typed model predictions."""

    seed_id: str
    observed_artist_count: int = Field(ge=1)
    state: Literal["supported", "abstained_insufficient_shared_artists"]
    peers: tuple[ModelPeer, ...] = Field(max_length=20)
    artist_candidates: tuple[ArtistProposal, ...] = Field(max_length=20)


def source_graph_positions(rows: tuple[ModelGenre, ...]) -> dict[str, tuple[float, float]]:
    """Place only peer-supported endpoints using existing deterministic graph geometry."""
    known = {row.seed_id for row in rows}
    weights: dict[tuple[str, str], float] = {}
    for row in rows:
        for peer in row.peers:
            if peer.seed_id not in known or peer.seed_id == row.seed_id:
                raise ValueError("model peer references an unknown or self genre")
            left, right = sorted((row.seed_id, peer.seed_id))
            weights[left, right] = max(weights.get((left, right), 0.0), peer.score)
    connected = tuple(sorted({seed for pair in weights for seed in pair}))
    coordinates = build_weighted_spectral_coordinates(connected, weights)
    atlas = build_rectangular_atlas(
        tuple(
            AtlasPoint(point.genre_id, float(point.x), float(point.y), str(point.component))
            for point in coordinates
        )
    )
    return {seed: (round(x, 10), round(y, 10)) for seed, (x, y) in atlas.positions.items()}


def exact_native_label(
    seed: str, native_ids: set[str], labels: Mapping[str, str]
) -> tuple[str, str]:
    """Use a single exact native UUID; ambiguous or absent joins keep an opaque ID."""
    if len(native_ids) == 1:
        identifier = next(iter(native_ids))
        if name := labels.get(identifier):
            return name, "exact_native_uuid"
    return f"Unresolved genre · {seed}", "ambiguous_native_uuid" if len(
        native_ids
    ) > 1 else "missing_native_label"


def _source_rows(  # noqa: C901, PLR0912 - batch exact joins and inference exclusions share one source boundary.
    connection: sqlite3.Connection,
    rows: tuple[ModelGenre, ...],
    proposal_verifier: Callable[[str, ArtistProposal], None] | None = None,
) -> tuple[dict[str, list[str]], dict[str, dict[str, object]], dict[str, set[str]]]:
    examples: dict[str, list[str]] = defaultdict(list)
    source_counts: dict[str, int] = defaultdict(int)
    native: dict[str, set[str]] = defaultdict(set)
    for seed, artist in connection.execute(
        "SELECT seed_id,artist_mbid FROM seed_artist ORDER BY seed_id,artist_mbid"
    ):
        source_counts[str(seed)] += 1
        if len(examples[str(seed)]) < EXAMPLE_LIMIT:
            examples[str(seed)].append(str(artist))
    if source_counts != {row.seed_id: row.observed_artist_count for row in rows}:
        raise ValueError("model observation counts differ from the exact catalog projection")
    for seed, identifier in connection.execute(
        "SELECT DISTINCT seed_id,musicbrainz_genre_id FROM direct_claim "
        "ORDER BY seed_id,musicbrainz_genre_id"
    ):
        native[str(seed)].add(str(identifier))
    selected = {artist for artists in examples.values() for artist in artists}
    selected.update(proposal.artist_mbid for row in rows for proposal in row.artist_candidates)
    artists: dict[str, dict[str, object]] = {}
    for artist, display, status in connection.execute(
        "SELECT artist_mbid,display_name,name_status FROM artist ORDER BY artist_mbid"
    ):
        if artist in selected:
            artists[str(artist)] = {
                "name": str(display) if display else str(artist),
                "name_status": str(status),
                "genre_ids": [],
            }
    if set(artists) != selected:
        raise ValueError("model artist proposal references an artist outside the source catalog")
    observed: dict[str, list[str]] = defaultdict(list)
    for seed, artist in connection.execute(
        "SELECT seed_id,artist_mbid FROM seed_artist ORDER BY artist_mbid,seed_id"
    ):
        if artist in selected:
            observed[str(artist)].append(str(seed))
    for artist, values in artists.items():
        values["genre_ids"] = observed[artist]
    for row in rows:
        peers = {peer.seed_id for peer in row.peers}
        for proposal in row.artist_candidates:
            if row.seed_id in observed[proposal.artist_mbid]:
                raise ValueError("inferred artist proposal was mixed with a direct observation")
            if proposal_verifier is not None:
                proposal_verifier(row.seed_id, proposal)
            elif (
                not proposal.via_seed_ids
                or set(proposal.via_seed_ids) != set(observed[proposal.artist_mbid]) & peers
                or proposal.opposing_seed_ids
            ):
                raise ValueError(
                    "artist proposal explanations do not replay exact source observations"
                )
    return dict(examples), artists, dict(native)


def assemble_preview(
    connection: sqlite3.Connection,
    rows: tuple[ModelGenre, ...],
    labels: Mapping[str, str],
    *,
    proposal_verifier: Callable[[str, ArtistProposal], None] | None = None,
) -> dict[str, object]:
    """Join presentation metadata after fitting coordinates from model scores alone."""
    positions = source_graph_positions(rows)
    examples, artists, native = _source_rows(connection, rows, proposal_verifier)
    genres = []
    for row in rows:
        name, status = exact_native_label(row.seed_id, native.get(row.seed_id, set()), labels)
        point = positions.get(row.seed_id)
        if (row.state == "supported") != (point is not None):
            raise ValueError("model abstention state differs from graph support")
        genres.append(
            {
                "id": row.seed_id,
                "name": name,
                "label_status": status,
                "native_genre_ids": sorted(native.get(row.seed_id, ())),
                "x": point[0] if point else None,
                "y": point[1] if point else None,
                "observed_artist_count": row.observed_artist_count,
                "direct_artist_ids": examples[row.seed_id],
                "direct_artist_role": "direct_source_observation",
                "direct_artist_order": "musicbrainz_id_ascending_not_relevance",
                "peers": [peer.model_dump(mode="json") for peer in row.peers],
                "proposals": [
                    proposal.model_dump(mode="json") for proposal in row.artist_candidates
                ],
            }
        )
    default = next(
        (str(genre["id"]) for genre in genres if genre["name"] == "jazz"), rows[0].seed_id
    )
    return {
        "revision": _REVISION,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "genres": genres,
        "artists": artists,
        "default_genre": default,
        "unplaced_count": len(rows) - len(positions),
    }


def _verify_source_agreement(
    model: Mapping[str, object], report: Mapping[str, object], catalog: object
) -> None:
    # Kept at the model/catalog seam so unrelated receipt-bound artifacts cannot mix.
    for field, catalog_field in (
        ("custody_object_sha256", "direct_object_sha256"),
        ("custody_receipt_output_sha256", "direct_receipt_output_sha256"),
    ):
        if model.get(field) != report.get(field) or report.get(field) != getattr(
            catalog, catalog_field
        ):
            raise ValueError("model and catalog source custody hashes differ")
    if any(
        payload.get("public_export_authorized") is not False
        or payload.get("serving_authorized") is not False
        or payload.get("scope") != "local_research_only"
        for payload in (model, report)
    ):
        raise ValueError("model does not retain its local research boundary")


def verify_observation_projection(index: ObservationIndex, connection: sqlite3.Connection) -> None:
    """Require every retained model matrix pair to equal the verified source projection."""
    expected = (
        (artist, index.seeds[int(column)])
        for row, artist in enumerate(index.artists)
        for column in sorted(
            index.binary.indices[index.binary.indptr[row] : index.binary.indptr[row + 1]]
        )
    )
    actual = connection.execute(
        "SELECT artist_mbid,seed_id FROM seed_artist ORDER BY artist_mbid,seed_id"
    )
    if any(left != right for left, right in itertools.zip_longest(expected, actual)):
        raise ValueError("model observation matrix differs from exact source catalog pairs")


def _load_preview_index(
    directory: Path,
    revision: object,
) -> tuple[ObservationIndex, Callable[[str, ArtistProposal], None] | None]:
    """Verify the selected model format and bind its explanation checker."""
    proposal_verifier = None
    if revision == "direct-custody-linear-reconstruction-v2":
        index, transfer = load_reconstruction(directory)

        def verify_signed(seed: str, proposal: ArtistProposal) -> None:
            verify_artist_proposal(
                index=index,
                transfer=transfer,
                seed_id=seed,
                artist_mbid=proposal.artist_mbid,
                score=proposal.score,
                via_seed_ids=proposal.via_seed_ids,
                opposing_seed_ids=proposal.opposing_seed_ids,
            )

        proposal_verifier = verify_signed
    else:
        index = load_neighborhood_index(directory)
    return index, proposal_verifier


def _load_display_overlay(
    catalog_directory: Path,
    artist_name_directory: Path | None,
) -> tuple[dict[str, object] | None, dict[str, str]]:
    """Join only independently replayed official exact-ID display labels."""
    name_enrichment = None
    display_names: dict[str, str] = {}
    if artist_name_directory is not None:
        name_enrichment = verify_artist_name_enrichment(
            catalog_directory=catalog_directory, directory=artist_name_directory
        )
        for row in TypeAdapter(list[dict[str, object]]).validate_python(name_enrichment["rows"]):
            if row["status"] == "exact":
                display_names[str(row["artist_mbid"])] = str(row["display_name"])
    return name_enrichment, display_names


def _bind_artist_navigation(
    payload: dict[str, object],
    artist_catalog: dict[str, object],
    display_names: Mapping[str, str],
) -> None:
    """Add complete navigation and display labels without changing direct evidence."""
    payload["artist_catalog"] = artist_catalog
    if not isinstance(payload["artists"], dict):
        raise TypeError("invalid embedded source artist projection")
    for artist, profile in payload["artists"].items():
        if artist in display_names:
            profile["name"] = display_names[artist]
            profile["name_status"] = "exact_official_name_overlay"
    page_counts = artist_catalog["genre_page_counts"]
    if not isinstance(page_counts, dict) or not isinstance(payload["genres"], list):
        raise TypeError("invalid complete artist navigation projection")
    for genre in payload["genres"]:
        genre["direct_artist_page_count"] = page_counts[genre["id"]]
        genre["direct_artist_page_size"] = artist_catalog["page_size"]


def _bind_release_navigation(payload: dict[str, object], summary: dict[str, object]) -> None:
    """Link exact credit metadata while retaining its separate evidence role."""
    artist_paths = summary["artist_paths"]
    genre_paths = summary["genre_paths"]
    if not isinstance(artist_paths, dict) or not isinstance(genre_paths, dict):
        raise TypeError("invalid release context routing projection")
    payload["release_contexts"] = {
        "artist_paths": artist_paths,
        "genre_paths": genre_paths,
        "output_sha256": summary["output_sha256"],
        "missing_context_status": summary["missing_context_status"],
    }
    genres = payload["genres"]
    if not isinstance(genres, list):
        raise TypeError("invalid release genre navigation projection")
    for genre in genres:
        if genre["id"] in genre_paths:
            genre["release_context_path"] = genre_paths[genre["id"]]


def build_local_direct_custody_preview(
    *,
    model_directory: Path,
    catalog_directory: Path,
    label_directory: Path,
    output: Path,
    artist_name_directory: Path | None = None,
) -> dict[str, object]:
    """Verify all independent receipts once and write a fresh static local explorer."""
    require_local_candidate_destination(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace a local preview")
    report = json.loads((model_directory / "report.json").read_bytes())
    index, proposal_verifier = _load_preview_index(model_directory, report.get("revision"))
    model = json.loads((model_directory / "model.json").read_bytes())
    catalog = verify_local_musicbrainz_candidate_catalog(directory=catalog_directory)
    _verify_source_agreement(model, report, catalog)
    name_enrichment, display_names = _load_display_overlay(catalog_directory, artist_name_directory)
    labels = verify_native_musicbrainz_genre_labels(directory=label_directory)
    native_labels = {
        str(row["musicbrainz_genre_id"]): str(row["display_name"])
        for row in TypeAdapter(list[dict[str, str | None]]).validate_python(labels["genres"])
        if row["display_name"]
    }
    rows = TypeAdapter(tuple[ModelGenre, ...]).validate_json(canonical_json(model["genres"]))
    if not rows or tuple(row.seed_id for row in rows) != index.seeds:
        raise ValueError("model genre rows do not match verified source identities")
    database = catalog_directory / "catalog.sqlite"
    with closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        verify_observation_projection(index, connection)
        payload = assemble_preview(
            connection, rows, native_labels, proposal_verifier=proposal_verifier
        )
    selected = report["test"][report["selected_arm"]]
    recall = float(selected["recall_at_10"])
    if not math.isfinite(recall) or not 0 <= recall <= 1:
        raise ValueError("invalid evaluation metric")
    payload.update(
        {
            "artist_count": catalog.artist_count,
            "evaluation_note": (
                f"The model recovered {recall:.2%} of held-out direct source genres in its "
                "top 10 artist-to-genre predictions. This does not evaluate the "
                "genre-to-artist proposals or map geometry."
            ),
            "catalog_output_sha256": catalog.output_sha256,
            "model_report_output_sha256": report["output_sha256"],
            "native_labels_output_sha256": labels["output_sha256"],
        }
    )
    output.mkdir(parents=True)
    with closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        artist_catalog = write_direct_artist_shards(connection, output, display_names=display_names)
    if artist_catalog["artist_count"] != catalog.artist_count:
        raise ValueError("complete artist projection differs from verified source catalog")
    _bind_artist_navigation(payload, artist_catalog, display_names)
    artist_maps = build_genre_artist_maps(index, output_directory=output / "genre-artist-maps")
    join_artist_map_labels(payload, output)
    payload["artist_maps_revision"] = "direct-source-artist-overlap-maps-v1"
    release_contexts = write_artist_release_contexts(
        direct_catalog_directory=catalog_directory, output_directory=output
    )
    _bind_release_navigation(payload, release_contexts)
    write_genre_detail_shards(payload, output)
    (output / "data.json").write_bytes(canonical_json(payload) + b"\n")
    for source, target in (
        ("direct-custody-preview.html", "index.html"),
        ("direct-custody-preview.js", "direct-custody-preview.js"),
        ("direct-custody-preview.css", "direct-custody-preview.css"),
    ):
        shutil.copyfile(_STATIC / source, output / target)
    receipt: dict[str, object] = {
        "revision": _REVISION,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "historical_coordinates_or_names_read": False,
        "layout_method": "weighted_spectral_union_max_directional_score_then_rectangular_atlas",
        "layout_inputs": "model_genre_peer_edges_only",
        "artist_examples_order": "exact_artist_mbid_ascending_not_relevance",
        "complete_artist_catalog": artist_catalog,
        "artist_maps": artist_maps,
        "release_contexts": release_contexts,
        "release_context_builder_sha256": sha256_file(
            Path(__file__).parents[1] / "catalog/musicbrainz_release_context.py"
        )[0],
        "artist_map_builder_sha256": sha256_file(
            Path(__file__).parents[1] / "ml/direct_custody_artist_maps.py"
        )[0],
        "artist_shard_builder_sha256": sha256_file(
            Path(__file__).with_name("direct_artist_shards.py")
        )[0],
        "genre_label_role": "exact_native_uuid_display_only",
        "model_report_output_sha256": report["output_sha256"],
        "model_sha256": sha256_file(model_directory / "model.json")[0],
        "catalog_output_sha256": catalog.output_sha256,
        "native_labels_output_sha256": labels["output_sha256"],
        "artist_name_enrichment_output_sha256": (
            name_enrichment["output_sha256"] if name_enrichment else None
        ),
        "artist_name_role": "display_only_exact_mbid_no_membership_change",
        "direct_object_sha256": catalog.direct_object_sha256,
        "name_object_sha256": catalog.name_object_sha256,
        "builder_sha256": sha256_file(Path(__file__))[0],
        "spectral_engine_sha256": sha256_file(Path(__file__).parents[1] / "ml/layout_lenses.py")[0],
        "atlas_engine_sha256": sha256_file(
            Path(__file__).parents[1] / "ml/semantic_layout/atlas.py"
        )[0],
        "seed_count": len(rows),
        "unplaced_count": payload["unplaced_count"],
        "files": {
            path.relative_to(output).as_posix(): {
                "sha256": sha256_file(path)[0],
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / "preview-receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt
