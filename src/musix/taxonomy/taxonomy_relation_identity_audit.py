"""Audit exact-QID limits of a source-neutral taxonomy relation expansion."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.common import canonical_json, sha256_hex
from musix.models import FrozenModel
from musix.types import Sha256  # noqa: TC001  # Pydantic resolves this Annotated alias at runtime.

if TYPE_CHECKING:
    from musix.taxonomy.taxonomy_relation_expansion import TaxonomyRelationExpansionArtifact

_QID: Final[re.Pattern[str]] = re.compile(r"wd:(Q[1-9][0-9]*)")
_SEED_COUNT: Final = 6_291


class TaxonomyRelationIdentityAudit(FrozenModel):
    """Explain the bounded exact-identity ceiling without proposing new facts."""

    revision: Literal["taxonomy-relation-identity-audit-v1"] = "taxonomy-relation-identity-audit-v1"
    expansion_output_sha256: Sha256
    seed_count: Literal[6291] = 6291
    exact_qid_mapped_seed_count: int = Field(ge=0, le=6291)
    accepted_factual_edge_count: int = Field(ge=0)
    skipped_unknown_endpoint_count: int = Field(ge=0)
    skipped_ambiguous_exact_qid_count: int = Field(ge=0)
    current_query_qid_count: int = Field(ge=0)
    stale_query_qid_count: int = Field(ge=0)
    stale_query_is_current_subset: bool
    historical_data_used_for_construction: Literal[False] = False
    output_sha256: Sha256


def qids_from_query(query: str) -> frozenset[str]:
    """Return only explicit Wikidata QIDs from the query's bounded VALUES clause."""
    matches: set[str] = set()
    for match in _QID.findall(query):
        matches.add(match)
    return frozenset(matches)


def audit_taxonomy_relation_identity(
    expansion: TaxonomyRelationExpansionArtifact,
    *,
    current_query: str,
    stale_query: str,
) -> TaxonomyRelationIdentityAudit:
    """Report why a stale exact-QID query cannot expand the sealed projection."""
    if expansion.coverage.seed_count != _SEED_COUNT:
        raise ValueError("taxonomy expansion must retain the complete 6291-seed universe")
    current_qids = qids_from_query(current_query)
    stale_qids = qids_from_query(stale_query)
    provisional = TaxonomyRelationIdentityAudit(
        expansion_output_sha256=expansion.output_sha256,
        exact_qid_mapped_seed_count=expansion.coverage.exact_qid_mapped_seed_count,
        accepted_factual_edge_count=expansion.coverage.accepted_factual_edge_count,
        skipped_unknown_endpoint_count=expansion.coverage.skipped_unknown_endpoint_count,
        skipped_ambiguous_exact_qid_count=expansion.coverage.skipped_ambiguous_exact_qid_count,
        current_query_qid_count=len(current_qids),
        stale_query_qid_count=len(stale_qids),
        stale_query_is_current_subset=stale_qids <= current_qids,
        output_sha256="0" * 64,
    )
    payload = canonical_json(provisional.model_dump(mode="json", exclude={"output_sha256"}))
    return provisional.model_copy(update={"output_sha256": sha256_hex(payload)})
