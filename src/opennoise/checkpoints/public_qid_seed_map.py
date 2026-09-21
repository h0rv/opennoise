"""Construct a sealed, public-only QID-to-positioned-seed mapping receipt.

The mapping is deliberately lexical and conservative.  It reads only the
sealed public catalog and the canonical semantic layout; it does not open seed
reconciliation, v3 candidate, static-export, or research inputs.  Exact
normalized names and public catalog aliases are admissible, while every
ambiguous label and every QID with more than one positioned seed is retained
as an explicit abstention.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)
from opennoise.models import FrozenModel
from opennoise.taxonomy.seeds.universe import normalize_label
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "public-qid-seed-map-v1"
_PUBLIC_DATABASE_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_CANONICAL_LAYOUT_FILE_SHA256: Final = (
    "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
)
_CANONICAL_LAYOUT_LOGICAL_SHA256: Final = (
    "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"
)
_OUTPUT_SHA256: Final = "dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449"


class PublicQidSeedMapError(ValueError):
    """A sealed public QID mapping cannot be replayed safely."""


class PublicQidSeedMapInputs(FrozenModel):
    """The only two construction inputs accepted by this receipt."""

    public_database: Path
    canonical_layout: Path


class InputReceipt(FrozenModel):
    """Byte and logical identity of one directly consumed sealed input."""

    role: Literal["public_database", "canonical_layout"]
    byte_sha256: Sha256
    byte_count: int = Field(gt=0)
    logical_sha256: Sha256 | None = None


class PublicQidIdentity(FrozenModel):
    """One approved public catalog genre identity matched by a label."""

    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)


class AmbiguousLabelAbstention(FrozenModel):
    """A normalized label with multiple public genre identities."""

    normalized_label: str = Field(min_length=1)
    identities: tuple[PublicQidIdentity, ...] = Field(min_length=2)
    disposition: Literal["abstain_ambiguous_public_label"] = "abstain_ambiguous_public_label"

    @model_validator(mode="after")
    def _distinct_identities(self) -> AmbiguousLabelAbstention:
        if len(set(self.identities)) != len(self.identities):
            raise ValueError("ambiguous label identities must be distinct")
        return self


class SeedQidLink(FrozenModel):
    """One unambiguous exact normalized public label link."""

    seed_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    match_kind: Literal["canonical", "alias"]


class ReverseQidAbstention(FrozenModel):
    """A QID with multiple positioned seeds, which cannot choose a map context."""

    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    seed_ids: tuple[str, ...] = Field(min_length=2)
    disposition: Literal["abstain_multiple_positioned_seeds"] = "abstain_multiple_positioned_seeds"


class QidSeedMapEntry(FrozenModel):
    """The sole automatically eligible QID-to-positioned-seed binding."""

    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    seed_id: str = Field(min_length=1)
    binding: Literal["one_to_one_qid_position_binding"] = "one_to_one_qid_position_binding"


class PublicQidSeedMapCoverage(FrozenModel):
    """Logical accounting that makes all abstention boundaries observable."""

    layout_seed_count: int = Field(ge=1)
    positioned_seed_count: int = Field(ge=0)
    unique_seed_qid_link_count: int = Field(ge=0)
    ambiguous_label_count: int = Field(ge=0)
    positioned_seed_qid_link_count: int = Field(ge=0)
    positioned_qid_count: int = Field(ge=0)
    reverse_qid_abstention_count: int = Field(ge=0)
    one_to_one_positioned_qid_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _replay_bounds(self) -> PublicQidSeedMapCoverage:
        if self.positioned_seed_qid_link_count > self.unique_seed_qid_link_count:
            raise ValueError("positioned links exceed all unambiguous links")
        if (
            self.one_to_one_positioned_qid_count + self.reverse_qid_abstention_count
            != self.positioned_qid_count
        ):
            raise ValueError("positioned QID partition does not replay")
        return self


class PublicQidSeedMap(FrozenModel):
    """A non-promoted receipt suitable only for later release qualification."""

    revision: Literal["public-qid-seed-map-v1"] = _REVISION
    publication_scope: Literal["release_qualification_candidate_only"] = (
        "release_qualification_candidate_only"
    )
    static_output_written: Literal[False] = False
    promotion_performed: Literal[False] = False
    experimental_reconciliation_used: Literal[False] = False
    source_receipts: tuple[InputReceipt, InputReceipt]
    seed_links: tuple[SeedQidLink, ...]
    ambiguous_label_abstentions: tuple[AmbiguousLabelAbstention, ...]
    reverse_qid_abstentions: tuple[ReverseQidAbstention, ...]
    mappings: tuple[QidSeedMapEntry, ...]
    coverage: PublicQidSeedMapCoverage
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete_receipt(self) -> PublicQidSeedMap:
        if len({item.seed_id for item in self.seed_links}) != len(self.seed_links):
            raise ValueError("unambiguous seed links must have unique seed IDs")
        if len({item.qid for item in self.mappings}) != len(self.mappings):
            raise ValueError("mappings must have globally unique QIDs")
        if len({item.qid for item in self.reverse_qid_abstentions}) != len(
            self.reverse_qid_abstentions
        ):
            raise ValueError("reverse abstentions must have globally unique QIDs")
        if {item.qid for item in self.mappings} & {
            item.qid for item in self.reverse_qid_abstentions
        }:
            raise ValueError("a reverse-ambiguous QID cannot be automatically mapped")
        if len(self.mappings) != self.coverage.one_to_one_positioned_qid_count:
            raise ValueError("mapping count does not match one-to-one coverage")
        if tuple(item.role for item in self.source_receipts) != (
            "public_database",
            "canonical_layout",
        ):
            raise ValueError("source receipts must retain the sealed construction order")
        return self


def public_qid_seed_map_sha256(receipt: PublicQidSeedMap) -> Sha256:
    """Hash the receipt independently of its self-hash field."""
    return sha256_hex(canonical_json(receipt.model_dump(mode="json", exclude={"output_sha256"})))


def build_public_qid_seed_map(inputs: PublicQidSeedMapInputs) -> PublicQidSeedMap:
    """Build the bounded map exclusively from the two sealed construction inputs."""
    database_receipt = _require_pinned_file(
        inputs.public_database, _PUBLIC_DATABASE_SHA256, "public database", "public_database"
    )
    layout, layout_receipt = _load_pinned_layout(inputs.canonical_layout)
    labels = _load_public_labels(inputs.public_database)
    all_seeds = tuple(
        sorted(
            ((item.seed_id, item.name) for item in (*layout.coordinates, *layout.unplaced)),
            key=lambda item: item[0],
        )
    )
    positioned_seed_ids = {item.seed_id for item in layout.coordinates}
    seed_links, ambiguous = _resolve_seed_links(all_seeds, labels)
    mappings, reverse_abstentions = _resolve_positioned_qids(seed_links, positioned_seed_ids)
    coverage = PublicQidSeedMapCoverage(
        layout_seed_count=len(all_seeds),
        positioned_seed_count=len(positioned_seed_ids),
        unique_seed_qid_link_count=len(seed_links),
        ambiguous_label_count=len(ambiguous),
        positioned_seed_qid_link_count=sum(
            item.seed_id in positioned_seed_ids for item in seed_links
        ),
        positioned_qid_count=len(
            {item.qid for item in seed_links if item.seed_id in positioned_seed_ids}
        ),
        reverse_qid_abstention_count=len(reverse_abstentions),
        one_to_one_positioned_qid_count=len(mappings),
    )
    base = PublicQidSeedMap(
        source_receipts=(database_receipt, layout_receipt),
        seed_links=seed_links,
        ambiguous_label_abstentions=ambiguous,
        reverse_qid_abstentions=reverse_abstentions,
        mappings=mappings,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": public_qid_seed_map_sha256(base)})
    _require_expected_coverage(receipt)
    if receipt.output_sha256 != _OUTPUT_SHA256:
        raise PublicQidSeedMapError("pinned public QID mapping selection hash does not match")
    return receipt


def write_public_qid_seed_map(receipt: PublicQidSeedMap, output: Path) -> Sha256:
    """Create a deterministic immutable receipt file, never a static site asset."""
    _verify_receipt(receipt)
    payload = canonical_json(receipt.model_dump(mode="json")) + b"\n"
    _write_fresh_bytes(output, payload)
    byte_sha256, _ = sha256_file(output)
    return byte_sha256


def load_public_qid_seed_map(path: Path) -> PublicQidSeedMap:
    """Parse a receipt only after replaying its source ordering and self-hash."""
    try:
        receipt = PublicQidSeedMap.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise PublicQidSeedMapError("public QID seed-map receipt is invalid") from error
    _verify_receipt(receipt)
    return receipt


def _verify_receipt(receipt: PublicQidSeedMap) -> None:
    if receipt.output_sha256 != public_qid_seed_map_sha256(receipt):
        raise PublicQidSeedMapError("receipt logical hash does not replay")
    if receipt.output_sha256 != _OUTPUT_SHA256:
        raise PublicQidSeedMapError("pinned public QID mapping selection hash does not match")
    database, layout = receipt.source_receipts
    if (
        database.byte_sha256 != _PUBLIC_DATABASE_SHA256
        or layout.byte_sha256 != _CANONICAL_LAYOUT_FILE_SHA256
        or layout.logical_sha256 != _CANONICAL_LAYOUT_LOGICAL_SHA256
    ):
        raise PublicQidSeedMapError("receipt source pins do not match")
    _require_expected_coverage(receipt)


def _write_fresh_bytes(output: Path, payload: bytes) -> None:
    """Publish one receipt with link-based no-replace semantics and durable bytes."""
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise PublicQidSeedMapError("refusing to overwrite an existing receipt") from error
        directory_descriptor = os.open(output.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _require_pinned_file(
    path: Path,
    expected_sha256: Sha256,
    role: str,
    receipt_role: Literal["public_database", "canonical_layout"],
) -> InputReceipt:
    try:
        actual_sha256, byte_count = sha256_file(path)
    except OSError as error:
        raise PublicQidSeedMapError(f"cannot read pinned {role}") from error
    if actual_sha256 != expected_sha256:
        raise PublicQidSeedMapError(f"pinned {role} hash does not match")
    return InputReceipt(role=receipt_role, byte_sha256=actual_sha256, byte_count=byte_count)


def _load_pinned_layout(path: Path) -> tuple[SemanticLayoutArtifact, InputReceipt]:
    receipt = _require_pinned_file(
        path, _CANONICAL_LAYOUT_FILE_SHA256, "canonical layout", "canonical_layout"
    )
    try:
        layout = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
        verify_semantic_map_layout(layout)
    except (OSError, ValueError) as error:
        raise PublicQidSeedMapError("canonical layout is invalid") from error
    if layout.output_sha256 != _CANONICAL_LAYOUT_LOGICAL_SHA256:
        raise PublicQidSeedMapError("canonical layout logical hash does not match")
    return layout, receipt.model_copy(update={"logical_sha256": layout.output_sha256})


def _load_public_labels(
    database_path: Path,
) -> dict[str, tuple[tuple[PublicQidIdentity, Literal["canonical", "alias"]], ...]]:
    """Read only public target-genre identities and their catalog labels."""
    try:
        with closing(
            sqlite3.connect(
                f"file:{database_path.resolve(strict=True)}?mode=ro&immutable=1", uri=True
            )
        ) as database:
            rows = database.execute(
                """WITH eligible_genres AS (
                       SELECT DISTINCT genre.id, identifier.normalized_value AS qid, genre.name
                       FROM genres AS genre
                       JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
                       JOIN identifier_types AS identifier_type
                         ON identifier_type.id = identifier.identifier_type_id
                       JOIN provenance_records AS identifier_provenance
                         ON identifier_provenance.id = identifier.provenance_id
                       JOIN data_sources AS identifier_source
                         ON identifier_source.id = identifier_provenance.source_id
                       JOIN rights_policies AS identifier_policy
                         ON identifier_policy.id = identifier_provenance.policy_id
                       JOIN active_rights_policy_permissions AS identifier_export_permission
                         ON identifier_export_permission.policy_id = identifier_provenance.policy_id
                        AND identifier_export_permission.use_kind = 'export'
                        AND identifier_export_permission.decision = 'allow'
                       JOIN active_rights_policy_permissions AS identifier_display_permission
                         ON identifier_display_permission.policy_id
                            = identifier_provenance.policy_id
                        AND identifier_display_permission.use_kind = 'display'
                        AND identifier_display_permission.decision = 'allow'
                       WHERE genre.entity_kind = 'genre'
                         AND identifier_type.type_key = 'wikidata_genre_qid'
                         AND identifier.namespace = 'wikidata'
                         AND identifier_source.license_name LIKE 'CC0-1.0%'
                         AND identifier_policy.local_only = 0
                         AND EXISTS (
                             SELECT 1
                             FROM entity_provenance AS link
                             JOIN provenance_records AS provenance
                               ON provenance.id = link.provenance_id
                             JOIN data_sources AS source ON source.id = provenance.source_id
                             JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                             JOIN active_rights_policy_permissions AS export_permission
                               ON export_permission.policy_id = provenance.policy_id
                              AND export_permission.use_kind = 'export'
                              AND export_permission.decision = 'allow'
                             JOIN active_rights_policy_permissions AS display_permission
                               ON display_permission.policy_id = provenance.policy_id
                              AND display_permission.use_kind = 'display'
                              AND display_permission.decision = 'allow'
                             WHERE link.entity_id = genre.id
                               AND source.license_name LIKE 'CC0-1.0%'
                               AND policy.local_only = 0
                         )
                   ), approved_names AS (
                       SELECT name.entity_id, name.name
                       FROM entity_names AS name
                       JOIN provenance_records AS provenance ON provenance.id = name.provenance_id
                       JOIN data_sources AS source ON source.id = provenance.source_id
                       JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                       JOIN active_rights_policy_permissions AS export_permission
                         ON export_permission.policy_id = provenance.policy_id
                        AND export_permission.use_kind = 'export'
                        AND export_permission.decision = 'allow'
                       JOIN active_rights_policy_permissions AS display_permission
                         ON display_permission.policy_id = provenance.policy_id
                        AND display_permission.use_kind = 'display'
                        AND display_permission.decision = 'allow'
                       WHERE source.license_name LIKE 'CC0-1.0%'
                         AND policy.local_only = 0
                   )
                   SELECT genre.id, genre.qid, genre.name, 'canonical' AS match_kind
                   FROM eligible_genres AS genre
                   JOIN approved_names AS canonical_name
                     ON canonical_name.entity_id = genre.id
                    AND canonical_name.name = genre.name
                   UNION ALL
                   SELECT genre.id, genre.qid, alias.name, 'alias' AS match_kind
                   FROM eligible_genres AS genre
                   JOIN approved_names AS alias ON alias.entity_id = genre.id
                   ORDER BY 2, 1, 4, 3"""
            ).fetchall()
    except sqlite3.Error as error:
        raise PublicQidSeedMapError(
            "public database cannot replay approved genre labels"
        ) from error
    qid_catalog_ids: dict[str, set[int]] = defaultdict(set)
    for catalog_genre_id, qid, _, _ in rows:
        qid_catalog_ids[str(qid)].add(int(catalog_genre_id))
    duplicated_qids = sorted(qid for qid, ids in qid_catalog_ids.items() if len(ids) != 1)
    if duplicated_qids:
        raise PublicQidSeedMapError("one public QID must identify exactly one catalog genre")
    labels: dict[str, dict[PublicQidIdentity, Literal["canonical", "alias"]]] = defaultdict(dict)
    for catalog_genre_id, qid, name, match_kind in rows:
        identity = PublicQidIdentity(qid=str(qid), catalog_genre_id=int(catalog_genre_id))
        normalized = normalize_label(str(name))
        if not normalized:
            raise PublicQidSeedMapError("approved public genre label normalizes to empty")
        current = labels[normalized].get(identity)
        # Canonical is retained if the same identity is also listed as an alias.
        if current != "canonical":
            labels[normalized][identity] = match_kind
    return {
        label: tuple(
            sorted(candidates.items(), key=lambda item: (item[0].qid, item[0].catalog_genre_id))
        )
        for label, candidates in sorted(labels.items())
    }


def _resolve_seed_links(
    seeds: tuple[tuple[str, str], ...],
    labels: dict[str, tuple[tuple[PublicQidIdentity, Literal["canonical", "alias"]], ...]],
) -> tuple[tuple[SeedQidLink, ...], tuple[AmbiguousLabelAbstention, ...]]:
    """Accept a label only when it identifies exactly one public QID target."""
    links: list[SeedQidLink] = []
    ambiguous_by_label: dict[str, tuple[PublicQidIdentity, ...]] = {}
    for seed_id, seed_name in seeds:
        # Keep this boundary defensive even though the catalog reader already
        # coalesces duplicate canonical/alias spellings for one identity.
        candidate_kinds: dict[PublicQidIdentity, Literal["canonical", "alias"]] = {}
        for identity, match_kind in labels.get(normalize_label(seed_name), ()):
            if candidate_kinds.get(identity) != "canonical":
                candidate_kinds[identity] = match_kind
        candidates = tuple(
            sorted(
                candidate_kinds.items(), key=lambda item: (item[0].qid, item[0].catalog_genre_id)
            )
        )
        if len(candidates) == 1:
            identity, match_kind = candidates[0]
            links.append(
                SeedQidLink(
                    seed_id=seed_id,
                    seed_name=seed_name,
                    qid=identity.qid,
                    catalog_genre_id=identity.catalog_genre_id,
                    match_kind=match_kind,
                )
            )
        elif len(candidates) > 1:
            ambiguous_by_label[normalize_label(seed_name)] = tuple(
                identity for identity, _ in candidates
            )
    return (
        tuple(links),
        tuple(
            AmbiguousLabelAbstention(normalized_label=label, identities=identities)
            for label, identities in sorted(ambiguous_by_label.items())
        ),
    )


def _resolve_positioned_qids(
    seed_links: tuple[SeedQidLink, ...], positioned_seed_ids: set[str]
) -> tuple[tuple[QidSeedMapEntry, ...], tuple[ReverseQidAbstention, ...]]:
    """Reject, rather than choose from, a QID with multiple map seed contexts."""
    qid_catalog_ids: dict[str, set[int]] = defaultdict(set)
    grouped: dict[tuple[str, int], list[str]] = defaultdict(list)
    for item in seed_links:
        if item.seed_id in positioned_seed_ids:
            qid_catalog_ids[item.qid].add(item.catalog_genre_id)
            grouped[(item.qid, item.catalog_genre_id)].append(item.seed_id)
    if any(len(catalog_ids) != 1 for catalog_ids in qid_catalog_ids.values()):
        raise PublicQidSeedMapError("one positioned QID must identify exactly one catalog genre")
    mappings: list[QidSeedMapEntry] = []
    abstentions: list[ReverseQidAbstention] = []
    for (qid, catalog_genre_id), seed_ids in sorted(grouped.items()):
        unique_seed_ids = tuple(sorted(set(seed_ids)))
        if len(unique_seed_ids) == 1:
            mappings.append(
                QidSeedMapEntry(
                    qid=qid, catalog_genre_id=catalog_genre_id, seed_id=unique_seed_ids[0]
                )
            )
        else:
            abstentions.append(
                ReverseQidAbstention(
                    qid=qid, catalog_genre_id=catalog_genre_id, seed_ids=unique_seed_ids
                )
            )
    return tuple(mappings), tuple(abstentions)


def _require_expected_coverage(receipt: PublicQidSeedMap) -> None:
    expected = {
        "layout_seed_count": 6291,
        "positioned_seed_count": 2945,
        "unique_seed_qid_link_count": 441,
        "ambiguous_label_count": 37,
        "positioned_seed_qid_link_count": 409,
        "positioned_qid_count": 380,
        "reverse_qid_abstention_count": 25,
        "one_to_one_positioned_qid_count": 355,
    }
    if receipt.coverage.model_dump() != expected:
        raise PublicQidSeedMapError(
            f"pinned public QID mapping coverage drifted: {receipt.coverage.model_dump()}"
        )
