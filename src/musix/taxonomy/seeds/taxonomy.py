"""Public-only, name-led taxonomy anchors for the retained legacy vocabulary.

This is intentionally a review and navigation layer.  A lexical composition
such as ``canadian rock`` may be anchored to the public ``rock music`` genre,
but it never becomes an artist membership or a claimed public genre identity.
Historical geometry, historical neighbors, historical artists, and local NC
MusicBrainz research inputs have no construction path in this module.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from musix.common import sha256_file, sha256_hex, sha256_json
from musix.models import FrozenModel
from musix.taxonomy.seeds.universe import SeedInput, load_seed_input, normalize_label

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "genre-seed-public-taxonomy-v1"
_CC0_PREFIX: Final = "CC0-1.0"

type InferenceStatus = Literal[
    "canonical_exact",
    "canonical_alias",
    "anchored_compositional",
    "ambiguous_exact",
    "ambiguous_compositional",
    "abstained",
]
_INFERENCE_STATUSES: Final[tuple[InferenceStatus, ...]] = (
    "canonical_exact",
    "canonical_alias",
    "anchored_compositional",
    "ambiguous_exact",
    "ambiguous_compositional",
    "abstained",
)


class PublicTaxonomyConfig(FrozenModel):
    """Explicit bounded controls for public taxonomy anchoring."""

    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    max_ancestor_depth: int = Field(default=3, ge=1, le=8)
    max_ancestors_per_anchor: int = Field(default=8, ge=1, le=32)
    minimum_calibration_examples: int = Field(default=12, ge=1, le=10_000)


class PublicCatalogInput(FrozenModel):
    """A CC0 catalog snapshot permitted to enter a publishable artifact."""

    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_licenses: tuple[str, ...] = Field(min_length=1)
    public_domain_only: Literal[True] = True
    local_nc_research_excluded: Literal[True] = True


class PublicTaxonomyNode(FrozenModel):
    """One public catalog node used as an exact name or compositional anchor."""

    catalog_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    match_kind: Literal["canonical", "alias"]


class PublicTaxonomyAncestor(FrozenModel):
    """Observed public hierarchy evidence above a compositional anchor."""

    catalog_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    depth: int = Field(ge=1, le=8)
    relation_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class SeedTaxonomyInference(FrozenModel):
    """One explainable result or explicit abstention for every legacy name seed."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    status: InferenceStatus
    exact_candidates: tuple[PublicTaxonomyNode, ...] = ()
    lexical_modifier: str | None = None
    anchor: PublicTaxonomyNode | None = None
    anchor_ancestors: tuple[PublicTaxonomyAncestor, ...] = ()
    structural_confidence: float = Field(ge=0.0, le=1.0)
    confidence_is_membership_probability: Literal[False] = False
    canonical_membership_created: Literal[False] = False
    abstention_reason: str | None = None

    @model_validator(mode="after")
    def _enforce_honest_inference(self) -> SeedTaxonomyInference:
        anchored = self.status == "anchored_compositional"
        if anchored != (self.anchor is not None and self.lexical_modifier is not None):
            raise ValueError("compositional anchors require one modifier and one public anchor")
        if self.status.startswith("canonical_") and len(self.exact_candidates) != 1:
            raise ValueError("canonical exact or alias outcomes require one exact candidate")
        if self.status.startswith("ambiguous_") and not self.abstention_reason:
            raise ValueError("ambiguous outcomes require an abstention reason")
        if self.status == "abstained" and not self.abstention_reason:
            raise ValueError("abstained outcomes require an abstention reason")
        return self


class CompositionCalibration(FrozenModel):
    """Calibration against public exact-name hierarchy observations only."""

    eligible_exact_name_count: int = Field(ge=0)
    observed_taxonomy_path_count: int = Field(ge=0)
    missing_taxonomy_path_count: int = Field(ge=0)
    laplace_precision: float = Field(ge=0.0, le=1.0)
    status: Literal["available", "insufficient_examples"]
    minimum_examples: int = Field(ge=1)
    historical_data_read: Literal[False] = False
    local_nc_musicbrainz_read: Literal[False] = False


class TaxonomyCoverageReport(FrozenModel):
    """Coverage facts, distinguishing review anchors from canonical memberships."""

    seed_count: int = Field(ge=1)
    canonical_exact_count: int = Field(ge=0)
    canonical_alias_count: int = Field(ge=0)
    compositional_anchor_count: int = Field(ge=0)
    ambiguous_exact_count: int = Field(ge=0)
    ambiguous_compositional_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    covered_for_review_count: int = Field(ge=0)
    canonical_membership_count: int = Field(ge=0)
    inferred_membership_count: Literal[0] = 0


class GenreSeedPublicTaxonomyArtifact(FrozenModel):
    """Deterministic public-only expansion of the legacy name seed universe."""

    revision: Literal["genre-seed-public-taxonomy-v1"] = _REVISION
    seed_input: SeedInput
    public_catalog: PublicCatalogInput
    config: PublicTaxonomyConfig
    calibration: CompositionCalibration
    inferences: tuple[SeedTaxonomyInference, ...] = Field(min_length=1, max_length=20_000)
    coverage: TaxonomyCoverageReport
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_complete_seed_coverage(self) -> GenreSeedPublicTaxonomyArtifact:
        source_ids = {item.source_item_id for item in self.inferences}
        if source_ids != {item.source_item_id for item in self.seed_input.names}:
            raise ValueError("taxonomy inference must cover every name-only seed exactly once")
        if self.coverage.seed_count != len(self.inferences):
            raise ValueError("coverage seed count must match inferences")
        return self


@dataclass(frozen=True, slots=True)
class _CatalogGenre:
    row_id: int
    catalog_id: str
    name: str


@dataclass(frozen=True, slots=True)
class _LabelMatch:
    genre: _CatalogGenre
    match_kind: Literal["canonical", "alias"]


def _source_licenses(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT DISTINCT license_name FROM data_sources ORDER BY license_name"
    ).fetchall()
    licenses = tuple(str(row[0]) for row in rows if row[0])
    if not licenses or any(not license_name.startswith(_CC0_PREFIX) for license_name in licenses):
        raise ValueError("public taxonomy publication requires CC0-only catalog sources")
    return licenses


def _identity_map(connection: sqlite3.Connection) -> dict[int, str]:
    rows = connection.execute(
        """
        SELECT identifier.entity_id, identifier.normalized_value
        FROM entity_identifiers AS identifier
        JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
        WHERE type.type_key = 'wikidata_genre_qid'
        ORDER BY identifier.entity_id, identifier.normalized_value
        """
    ).fetchall()
    return {int(row_id): f"wikidata:genre:{value}" for row_id, value in rows}


def _read_catalog(
    connection: sqlite3.Connection,
) -> tuple[
    dict[str, tuple[_LabelMatch, ...]],
    dict[int, _CatalogGenre],
    dict[int, tuple[tuple[int, str], ...]],
]:
    identities = _identity_map(connection)
    rows = connection.execute(
        "SELECT id, name FROM genres WHERE entity_kind = 'genre' ORDER BY id"
    ).fetchall()
    genres = {
        int(row_id): _CatalogGenre(
            row_id=int(row_id),
            catalog_id=identities.get(int(row_id), f"public:genre:{row_id}"),
            name=str(name),
        )
        for row_id, name in rows
    }
    labels: dict[str, dict[int, _LabelMatch]] = defaultdict(dict)
    for genre in genres.values():
        labels[normalize_label(genre.name)][genre.row_id] = _LabelMatch(genre, "canonical")
    aliases = connection.execute(
        "SELECT entity_id, name FROM entity_names ORDER BY entity_id, name"
    ).fetchall()
    for row_id, name in aliases:
        genre = genres.get(int(row_id))
        if genre is not None:
            labels[normalize_label(str(name))].setdefault(genre.row_id, _LabelMatch(genre, "alias"))
    parents: dict[int, list[tuple[int, str]]] = defaultdict(list)
    hierarchy_rows = connection.execute(
        """SELECT child_genre_id, parent_genre_id, relation_id
           FROM genre_hierarchy
           ORDER BY child_genre_id, parent_genre_id, relation_id"""
    ).fetchall()
    for child, parent, relation_id in hierarchy_rows:
        if int(child) in genres and int(parent) in genres:
            parents[int(child)].append((int(parent), str(relation_id)))
    return (
        {key: tuple(value.values()) for key, value in labels.items()},
        genres,
        {key: tuple(value) for key, value in parents.items()},
    )


def _ancestors(
    genre: _CatalogGenre,
    genres: dict[int, _CatalogGenre],
    parents: dict[int, tuple[tuple[int, str], ...]],
    config: PublicTaxonomyConfig,
) -> tuple[PublicTaxonomyAncestor, ...]:
    queue: deque[tuple[int, int, tuple[str, ...]]] = deque(
        (parent, 1, (relation_id,)) for parent, relation_id in parents.get(genre.row_id, ())
    )
    seen: set[int] = set()
    result: list[PublicTaxonomyAncestor] = []
    while queue and len(result) < config.max_ancestors_per_anchor:
        row_id, depth, relation_ids = queue.popleft()
        if row_id in seen:
            continue
        seen.add(row_id)
        parent = genres[row_id]
        result.append(
            PublicTaxonomyAncestor(
                catalog_id=parent.catalog_id,
                name=parent.name,
                depth=depth,
                relation_ids=relation_ids,
            )
        )
        if depth < config.max_ancestor_depth:
            queue.extend(
                (next_id, depth + 1, (*relation_ids, relation_id))
                for next_id, relation_id in parents.get(row_id, ())
                if next_id not in seen
            )
    return tuple(result)


def _as_public_node(match: _LabelMatch) -> PublicTaxonomyNode:
    return PublicTaxonomyNode(
        catalog_id=match.genre.catalog_id, name=match.genre.name, match_kind=match.match_kind
    )


def _compositional_matches(
    normalized_name: str, labels: dict[str, tuple[_LabelMatch, ...]]
) -> tuple[tuple[str, _LabelMatch], ...]:
    tokens = normalized_name.split()
    candidates: dict[int, tuple[str, _LabelMatch]] = {}
    for offset in range(1, len(tokens)):
        modifier = " ".join(tokens[:offset])
        head = " ".join(tokens[offset:])
        matches = labels.get(head, ())
        if len(matches) == 1:
            match = matches[0]
            candidates.setdefault(match.genre.row_id, (modifier, match))
    return tuple(candidates[row_id] for row_id in sorted(candidates))


def _is_public_taxonomy_descendant(
    child: int, parent: int, parents: dict[int, tuple[tuple[int, str], ...]], max_depth: int
) -> bool:
    queue: deque[tuple[int, int]] = deque((item, 1) for item, _ in parents.get(child, ()))
    seen: set[int] = set()
    while queue:
        row_id, depth = queue.popleft()
        if row_id == parent:
            return True
        if row_id in seen or depth >= max_depth:
            continue
        seen.add(row_id)
        queue.extend((next_id, depth + 1) for next_id, _ in parents.get(row_id, ()))
    return False


def _calibration(
    seed: SeedInput,
    labels: dict[str, tuple[_LabelMatch, ...]],
    parents: dict[int, tuple[tuple[int, str], ...]],
    config: PublicTaxonomyConfig,
) -> CompositionCalibration:
    eligible = observed = 0
    for item in seed.names:
        exact = labels.get(normalize_label(item.name), ())
        compositional = _compositional_matches(normalize_label(item.name), labels)
        if len(exact) != 1 or len(compositional) != 1:
            continue
        target = exact[0].genre.row_id
        anchor = compositional[0][1].genre.row_id
        if target == anchor:
            continue
        eligible += 1
        observed += _is_public_taxonomy_descendant(
            target, anchor, parents, config.max_ancestor_depth
        )
    return CompositionCalibration(
        eligible_exact_name_count=eligible,
        observed_taxonomy_path_count=observed,
        missing_taxonomy_path_count=eligible - observed,
        laplace_precision=(observed + 1) / (eligible + 2),
        status="available"
        if eligible >= config.minimum_calibration_examples
        else "insufficient_examples",
        minimum_examples=config.minimum_calibration_examples,
    )


def _anchor_confidence(calibration: CompositionCalibration, ancestor_count: int) -> float:
    """Return a structural review priority, never an identity probability."""
    calibration_component = (
        calibration.laplace_precision if calibration.status == "available" else 0.5
    )
    return min(1.0, 0.45 + 0.35 * calibration_component + (0.05 if ancestor_count else 0.0))


def build_genre_seed_public_taxonomy(
    seed_artifact: Path,
    public_catalog_database: Path,
    *,
    config: PublicTaxonomyConfig | None = None,
) -> GenreSeedPublicTaxonomyArtifact:
    """Expand name coverage with CC0 taxonomy anchors without creating memberships."""
    config = config or PublicTaxonomyConfig()
    seed = load_seed_input(seed_artifact)
    if len(seed.names) != config.expected_seed_count:
        raise ValueError(
            f"expected {config.expected_seed_count} name seeds, found {len(seed.names)}"
        )
    with closing(
        sqlite3.connect(f"file:{public_catalog_database}?mode=ro", uri=True)
    ) as connection:
        licenses = _source_licenses(connection)
        labels, genres, parents = _read_catalog(connection)
    calibration = _calibration(seed, labels, parents, config)
    inferences: list[SeedTaxonomyInference] = []
    for item in seed.names:
        normalized = normalize_label(item.name)
        exact = labels.get(normalized, ())
        if len(exact) == 1:
            node = _as_public_node(exact[0])
            status: InferenceStatus = (
                "canonical_exact" if node.match_kind == "canonical" else "canonical_alias"
            )
            inferences.append(
                SeedTaxonomyInference(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    status=status,
                    exact_candidates=(node,),
                    structural_confidence=1.0,
                )
            )
            continue
        if len(exact) > 1:
            inferences.append(
                SeedTaxonomyInference(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    status="ambiguous_exact",
                    exact_candidates=tuple(_as_public_node(match) for match in exact),
                    structural_confidence=0.0,
                    abstention_reason=(
                        "multiple public catalog identities share the exact normalized name"
                    ),
                )
            )
            continue
        compositional = _compositional_matches(normalized, labels)
        if len(compositional) == 1:
            modifier, match = compositional[0]
            ancestors = _ancestors(match.genre, genres, parents, config)
            inferences.append(
                SeedTaxonomyInference(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    status="anchored_compositional",
                    lexical_modifier=modifier,
                    anchor=_as_public_node(match),
                    anchor_ancestors=ancestors,
                    structural_confidence=_anchor_confidence(calibration, len(ancestors)),
                )
            )
            continue
        if len(compositional) > 1:
            inferences.append(
                SeedTaxonomyInference(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalized,
                    status="ambiguous_compositional",
                    structural_confidence=0.0,
                    abstention_reason="multiple unique lexical suffix anchors disagree",
                )
            )
            continue
        inferences.append(
            SeedTaxonomyInference(
                source_item_id=item.source_item_id,
                source_external_id=item.source_external_id,
                seed_name=item.name,
                normalized_name=normalized,
                status="abstained",
                structural_confidence=0.0,
                abstention_reason="no unique exact public identity or lexical suffix anchor",
            )
        )
    counts = {
        status: sum(item.status == status for item in inferences) for status in _INFERENCE_STATUSES
    }
    coverage = TaxonomyCoverageReport(
        seed_count=len(inferences),
        canonical_exact_count=counts["canonical_exact"],
        canonical_alias_count=counts["canonical_alias"],
        compositional_anchor_count=counts["anchored_compositional"],
        ambiguous_exact_count=counts["ambiguous_exact"],
        ambiguous_compositional_count=counts["ambiguous_compositional"],
        abstained_count=counts["abstained"],
        covered_for_review_count=(
            counts["canonical_exact"] + counts["canonical_alias"] + counts["anchored_compositional"]
        ),
        canonical_membership_count=counts["canonical_exact"] + counts["canonical_alias"],
    )
    preliminary = GenreSeedPublicTaxonomyArtifact(
        seed_input=seed,
        public_catalog=PublicCatalogInput(
            database_sha256=sha256_file(public_catalog_database)[0], source_licenses=licenses
        ),
        config=config,
        calibration=calibration,
        inferences=tuple(inferences),
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(
        update={
            "output_sha256": sha256_json(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            )
        }
    )


def write_genre_seed_public_taxonomy(artifact: GenreSeedPublicTaxonomyArtifact, path: Path) -> str:
    """Write an idempotent typed artifact and return its byte hash."""
    if artifact.output_sha256 != sha256_json(
        artifact.model_dump(mode="json", exclude={"output_sha256"})
    ):
        raise ValueError("public taxonomy artifact logical hash does not match its content")
    payload = artifact.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return sha256_hex(payload.encode())
