"""Compact receipt-bound factual taxonomy overlay for a hierarchy candidate artifact."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import ijson
from pydantic import Field, model_validator

from musix.common import sha256_file, sha256_json
from musix.genre_hierarchy_candidates import (  # noqa: TC001
    GenreHierarchyCandidatePublicationReceipt,
)
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy_relation_expansion import (
    TaxonomyRelationExpansionArtifact,
    verify_taxonomy_relation_expansion,
)
from musix.types import Sha256  # noqa: TC001

_REVISION = "taxonomy-relation-hierarchy-overlay-v1"
_MAXIMUM_BASE_CANDIDATE_PAIR_COUNT = 250_000


def _stream_base_logical_hash(path: Path) -> Sha256:
    """Replay the base hierarchy's canonical logical hash without loading its edge list."""
    with path.open("rb") as stream:
        fields = tuple(
            value
            for prefix, event, value in ijson.parse(stream, use_float=True)
            if prefix == "" and event == "map_key"
        )
    if "output_sha256" not in fields or "candidates" not in fields or "seed_coverage" not in fields:
        raise ValueError("base hierarchy is missing required logical-hash fields")
    values: dict[str, object] = {}
    arrays = {"candidates", "seed_coverage"}
    for field in fields:
        if field == "output_sha256" or field in arrays:
            continue
        with path.open("rb") as stream:
            items = ijson.items(stream, field, use_float=True)
            try:
                values[field] = next(items)
            except StopIteration as error:
                raise ValueError(f"base hierarchy is missing {field!r}") from error
    digest = hashlib.sha256()
    digest.update(b"{")
    first = True
    for field in sorted(item for item in fields if item != "output_sha256"):
        if not first:
            digest.update(b",")
        first = False
        digest.update(json.dumps(field, ensure_ascii=False, separators=(",", ":")).encode())
        digest.update(b":")
        if field in arrays:
            digest.update(b"[")
            with path.open("rb") as stream:
                for index, item in enumerate(ijson.items(stream, f"{field}.item", use_float=True)):
                    if index:
                        digest.update(b",")
                    digest.update(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    )
            digest.update(b"]")
        else:
            digest.update(
                json.dumps(
                    values[field],
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            )
    digest.update(b"}")
    return digest.hexdigest()


class TaxonomyRelationHierarchyOverlayEdge(FrozenModel):
    """One direct factual delta or factual upgrade of a base pair."""

    child_genre_id: str = Field(min_length=1)
    parent_genre_id: str = Field(min_length=1)
    action: Literal["add", "upgrade_existing"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class TaxonomyRelationHierarchyOverlay(FrozenModel):
    """Small delta which references, rather than copies, a base hierarchy."""

    revision: Literal["taxonomy-relation-hierarchy-overlay-v1"] = _REVISION
    base_hierarchy_logical_output_sha256: Sha256
    base_hierarchy_receipt_sha256: Sha256
    base_hierarchy_object_key: ObjectKey
    base_hierarchy_object_sha256: Sha256
    base_hierarchy_object_byte_size: int = Field(ge=1)
    taxonomy_relation_expansion_output_sha256: Sha256
    maximum_base_candidate_pair_count: int = Field(
        default=_MAXIMUM_BASE_CANDIDATE_PAIR_COUNT, ge=1, le=1_000_000
    )
    edges: tuple[TaxonomyRelationHierarchyOverlayEdge, ...]
    base_candidate_count: int = Field(ge=0)
    base_accepted_count: int = Field(ge=0)
    union_candidate_count: int = Field(ge=0)
    union_accepted_count: int = Field(ge=0)
    net_new_accepted_count: int = Field(ge=0)
    isolated_seed_reduction: int = Field(ge=0)
    union_pair_sha256: Sha256
    output_sha256: Sha256

    @model_validator(mode="after")
    def bind_counts_and_hash(self) -> TaxonomyRelationHierarchyOverlay:
        """Bind pair uniqueness, union accounting, and the canonical hash."""
        pairs = tuple((edge.child_genre_id, edge.parent_genre_id) for edge in self.edges)
        if len(pairs) != len(set(pairs)):
            raise ValueError("overlay pairs must be unique")
        if self.union_candidate_count != self.base_candidate_count + self.net_new_accepted_count:
            raise ValueError("overlay union candidate count must add only novel pairs")
        if self.base_candidate_count > self.maximum_base_candidate_pair_count:
            raise ValueError("overlay base candidate pair count exceeds its explicit bound")
        if self.union_accepted_count < self.base_accepted_count:
            raise ValueError("overlay cannot remove accepted base edges")
        if (
            sha256_json(self.model_dump(mode="json", exclude={"output_sha256"}))
            != self.output_sha256
        ):
            raise ValueError("overlay logical hash does not replay")
        return self


class TaxonomyRelationHierarchyOverlayReceipt(FrozenModel):
    """Immutable object-store receipt for a compact hierarchy overlay."""

    artifact: ObjectWrite
    artifact_sha256: Sha256
    logical_output_sha256: Sha256


@dataclass(frozen=True)
class OverlayBaseInputs:
    """Trusted custody boundary for the immutable hierarchy base."""

    hierarchy_path: Path
    receipt: GenreHierarchyCandidatePublicationReceipt
    receipt_sha256: Sha256
    expected_receipt_sha256: Sha256
    object_store: ObjectStore


def _path_exists(parents: dict[str, set[str]], start: str, target: str) -> bool:
    pending, seen = [start], set[str]()
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node not in seen:
            seen.add(node)
            pending.extend(parents[node])
    return False


def _verify_overlay_base(base: OverlayBaseInputs) -> None:
    if base.receipt_sha256 != base.expected_receipt_sha256:
        raise ValueError("base hierarchy receipt does not match the explicit trust root")
    if (
        base.receipt.artifact.sha256 != base.receipt.artifact_sha256
        or base.receipt.artifact.byte_size < 1
    ):
        raise ValueError("base hierarchy receipt artifact fields are internally inconsistent")
    stored = base.object_store.inspect(base.receipt.artifact.key)
    if (
        stored.sha256 != base.receipt.artifact_sha256
        or stored.byte_size != base.receipt.artifact.byte_size
    ):
        raise ValueError("base hierarchy object does not match its trusted receipt")
    if sha256_file(base.hierarchy_path)[0] != base.receipt.artifact_sha256:
        raise ValueError("base hierarchy bytes do not match its receipt")
    with base.hierarchy_path.open("rb") as stream:
        try:
            declared_logical_hash = next(ijson.items(stream, "output_sha256"))
        except StopIteration as error:
            raise ValueError("base hierarchy is missing its logical output hash") from error
    if (
        declared_logical_hash != base.receipt.logical_output_sha256
        or _stream_base_logical_hash(base.hierarchy_path) != base.receipt.logical_output_sha256
    ):
        raise ValueError("base hierarchy logical hash does not replay its trusted receipt")


def build_taxonomy_relation_hierarchy_overlay(
    base: OverlayBaseInputs,
    relation_expansion: TaxonomyRelationExpansionArtifact,
    *,
    relation_source_store: ObjectStore,
) -> TaxonomyRelationHierarchyOverlay:
    """Stream base pair keys once; retain only a bounded factual delta in memory."""
    verify_taxonomy_relation_expansion(relation_expansion, source_store=relation_source_store)
    _verify_overlay_base(base)
    all_pairs: set[tuple[str, str]] = set()
    accepted_pairs: set[tuple[str, str]] = set()
    parents: dict[str, set[str]] = defaultdict(set)
    with base.hierarchy_path.open("rb") as stream:
        for candidate in ijson.items(stream, "candidates.item"):
            pair = (candidate["child_genre_id"], candidate["parent_genre_id"])
            all_pairs.add(pair)
            if candidate["status"] == "accepted":
                accepted_pairs.add(pair)
                parents[pair[0]].add(pair[1])
    if len(all_pairs) > _MAXIMUM_BASE_CANDIDATE_PAIR_COUNT:
        raise ValueError("base hierarchy candidate pair count exceeds overlay maximum")
    base_accepted_pairs = frozenset(accepted_pairs)
    edges: list[TaxonomyRelationHierarchyOverlayEdge] = []
    novel = 0
    for relation in relation_expansion.edges:
        if relation.disposition != "accepted_factual":
            continue
        pair = (relation.child_seed_id, relation.parent_seed_id)
        refs = tuple(
            f"taxonomy-relation-expansion:{relation_expansion.output_sha256}:{e.observation_id}"
            for e in relation.factual_evidence
        )
        if pair in accepted_pairs:
            continue
        if _path_exists(parents, pair[1], pair[0]):
            continue
        action: Literal["add", "upgrade_existing"] = (
            "upgrade_existing" if pair in all_pairs else "add"
        )
        edges.append(
            TaxonomyRelationHierarchyOverlayEdge(
                child_genre_id=pair[0], parent_genre_id=pair[1], action=action, evidence_refs=refs
            )
        )
        if pair not in all_pairs:
            novel += 1
        accepted_pairs.add(pair)
        parents[pair[0]].add(pair[1])
    receipt_sha = base.receipt_sha256
    union_pairs = tuple(
        sorted(all_pairs | {(edge.child_genre_id, edge.parent_genre_id) for edge in edges})
    )
    payload: dict[str, Any] = {
        "base_hierarchy_logical_output_sha256": base.receipt.logical_output_sha256,
        "base_hierarchy_receipt_sha256": receipt_sha,
        "base_hierarchy_object_key": base.receipt.artifact.key,
        "base_hierarchy_object_sha256": base.receipt.artifact_sha256,
        "base_hierarchy_object_byte_size": base.receipt.artifact.byte_size,
        "taxonomy_relation_expansion_output_sha256": relation_expansion.output_sha256,
        "maximum_base_candidate_pair_count": _MAXIMUM_BASE_CANDIDATE_PAIR_COUNT,
        "edges": tuple(edges),
        "base_candidate_count": len(all_pairs),
        "base_accepted_count": len(base_accepted_pairs),
        "union_candidate_count": len(all_pairs) + novel,
        "union_accepted_count": len(accepted_pairs),
        "net_new_accepted_count": novel,
        "isolated_seed_reduction": len({x for pair in accepted_pairs for x in pair})
        - len({x for pair in base_accepted_pairs for x in pair}),
        "union_pair_sha256": sha256_json(union_pairs),
        "output_sha256": "0" * 64,
    }
    provisional = TaxonomyRelationHierarchyOverlay.model_construct(**payload)
    payload["output_sha256"] = sha256_json(
        provisional.model_dump(mode="json", exclude={"output_sha256"})
    )
    return TaxonomyRelationHierarchyOverlay.model_validate(payload)


def publish_taxonomy_relation_hierarchy_overlay(
    overlay: TaxonomyRelationHierarchyOverlay, *, output: Path, store: ObjectStore
) -> TaxonomyRelationHierarchyOverlayReceipt:
    """Atomically publish the small overlay and bind both byte and logical hashes."""
    payload = (overlay.model_dump_json(indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    write = store.push(
        output,
        ObjectKey(value=f"taxonomy-relation-hierarchy-overlay/sha256/{overlay.output_sha256}.json"),
    )
    if write.sha256 != artifact_sha or write.byte_size != len(payload):
        raise ValueError("overlay object-store write does not match published bytes")
    return TaxonomyRelationHierarchyOverlayReceipt(
        artifact=write, artifact_sha256=artifact_sha, logical_output_sha256=overlay.output_sha256
    )
