"""Conservative, replayable Wikidata resolution for unresolved genre-name seeds.

This adapter deliberately receives only a name projection plus an existing
taxonomy outcome.  It does not open catalog SQLite files, artist evidence, or
any historical map fields.  A response may become an anchor only when exactly
one Wikidata item has an exact normalized English label or alias *and* direct
``music genre`` class/taxonomy evidence.  Everything else is retained as a
candidate or an explicit abstention.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from musix.common import canonical_json, sha256_file, sha256_hex, write_durable_bytes
from musix.taxonomy.genre_seed_universe import SeedInput, normalize_label
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "wikidata-genre-seed-resolver-v1"
_SPARQL_ENDPOINT: Final = "https://query.wikidata.org/sparql"
_MUSIC_GENRE_QID: Final = "Q188451"
_QID_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:^|/)(Q[1-9][0-9]*)$")
_TARGET_STATUSES: Final = frozenset({"ambiguous_exact", "ambiguous_compositional", "abstained"})

type TargetStatus = Literal["ambiguous_exact", "ambiguous_compositional", "abstained"]
type MatchKind = Literal["label", "alias"]
type AbstentionReason = Literal[
    "ambiguous_exact_wikidata_candidates",
    "no_exact_normalized_english_match",
    "unique_exact_match_lacks_music_genre_evidence",
    "offline_cache_miss",
    "wikidata_request_failed",
]


class _StrictModel(BaseModel):
    """Freeze every parsed boundary and reject unmodelled fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", populate_by_name=True)


class WikidataResolverConfig(_StrictModel):
    """Bounded request controls for one resolver invocation."""

    expected_seed_count: int = Field(default=6291, ge=1, le=20_000)
    batch_limit: int = Field(default=250, ge=1, le=250)
    sparql_terms_per_request: int = Field(default=25, ge=1, le=50)
    minimum_request_interval_seconds: float = Field(default=1.0, ge=1.0, le=60.0)
    max_retries: int = Field(default=3, ge=0, le=6)
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    user_agent: str = Field(min_length=8, max_length=300)


class WikidataSeedTarget(_StrictModel):
    """One eligible source name and the prior non-canonical taxonomy result."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    prior_status: TargetStatus


class WikidataResolverInput(_StrictModel):
    """Name-only input audit for one deterministic subset of the 6,291 seeds."""

    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_count: int = Field(ge=1)
    eligible_count: int = Field(ge=0)
    selected_targets: tuple[WikidataSeedTarget, ...] = Field(min_length=1, max_length=250)


class SparqlBinding(_StrictModel):
    """Strict subset of a SPARQL JSON binding."""

    type: Literal["uri", "literal", "typed-literal"]
    value: str
    language: str | None = Field(default=None, alias="xml:lang")
    datatype: str | None = None


class SparqlHead(_StrictModel):
    """Variable names declared by one SPARQL JSON response."""

    vars: tuple[str, ...]


class SparqlResults(_StrictModel):
    """Typed bindings emitted by one SPARQL JSON response."""

    bindings: tuple[dict[str, SparqlBinding], ...]


class SparqlResponse(_StrictModel):
    """The only remote response shape accepted by the resolver."""

    head: SparqlHead
    results: SparqlResults


class CachedSparqlResponse(_StrictModel):
    """Content-addressed, timestamp-free replay input for one SPARQL request."""

    revision: Literal["wikidata-sparql-cache-v1"] = "wikidata-sparql-cache-v1"
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: SparqlResponse


class WikidataCandidate(_StrictModel):
    """A retained exact label/alias candidate, never an artist association."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    english_label: str = Field(min_length=1)
    matched_english_name: str = Field(min_length=1)
    match_kind: MatchKind
    instance_of_qids: tuple[str, ...] = ()
    subclass_of_qids: tuple[str, ...] = ()
    has_direct_music_genre_evidence: bool
    artist_memberships_created: Literal[0] = 0


class AcceptedWikidataAnchor(_StrictModel):
    """A unique exact Wikidata item with direct music-genre evidence."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    wikidata_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    english_label: str = Field(min_length=1)
    matched_english_name: str = Field(min_length=1)
    match_kind: MatchKind
    class_or_taxonomy_evidence_qid: Literal["Q188451"] = _MUSIC_GENRE_QID
    confidence: float = Field(default=1.0, ge=1.0, le=1.0)
    canonical_membership_created: Literal[False] = False
    artist_memberships_created: Literal[0] = 0


class WikidataAbstention(_StrictModel):
    """A fail-closed result for a target that was not accepted as an anchor."""

    source_item_id: str = Field(min_length=1)
    source_external_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    reason: AbstentionReason
    candidate_qids: tuple[str, ...] = ()
    artist_memberships_created: Literal[0] = 0


class WikidataResolverCounts(_StrictModel):
    """Non-membership outcome counts for one bounded batch."""

    targets: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    accepted_exact_unique_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    ambiguity_count: int = Field(ge=0)
    offline_cache_miss_count: int = Field(ge=0)
    request_failure_count: int = Field(ge=0)
    artist_membership_count: Literal[0] = 0


class WikidataResolverRuntime(_StrictModel):
    """Observability data excluded from the reproducible logical content hash."""

    elapsed_seconds: float = Field(ge=0)
    request_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    offline_replay: bool


class WikidataSeedResolutionArtifact(_StrictModel):
    """One bounded, auditable batch with independent result collections."""

    revision: Literal["wikidata-genre-seed-resolver-v1"] = _REVISION
    input: WikidataResolverInput
    config: WikidataResolverConfig
    request_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: tuple[WikidataCandidate, ...] = ()
    accepted_exact_unique: tuple[AcceptedWikidataAnchor, ...] = ()
    abstentions: tuple[WikidataAbstention, ...] = ()
    counts: WikidataResolverCounts
    runtime: WikidataResolverRuntime
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _enforce_fail_closed_partition(self) -> WikidataSeedResolutionArtifact:
        target_ids = {target.source_item_id for target in self.input.selected_targets}
        output_ids = {item.source_item_id for item in self.accepted_exact_unique} | {
            item.source_item_id for item in self.abstentions
        }
        if target_ids != output_ids:
            raise ValueError("accepted anchors and abstentions must partition the selected targets")
        if len(output_ids) != len(self.accepted_exact_unique) + len(self.abstentions):
            raise ValueError("a target cannot be both accepted and abstained")
        candidate_target_ids = {item.source_item_id for item in self.candidates}
        if not candidate_target_ids <= target_ids:
            raise ValueError("candidate is outside the selected target batch")
        if self.counts.targets != len(target_ids):
            raise ValueError("target count does not match the selected batch")
        if self.counts.candidate_count != len(self.candidates):
            raise ValueError("candidate count does not match candidates")
        if self.counts.accepted_exact_unique_count != len(self.accepted_exact_unique):
            raise ValueError("accepted count does not match anchors")
        if self.counts.abstention_count != len(self.abstentions):
            raise ValueError("abstention count does not match abstentions")
        return self


class WikidataPublicAnchorMergeArtifact(_StrictModel):
    """An anchor-only merge projection; it has no membership construction path."""

    revision: Literal["wikidata-public-anchor-merge-v1"] = "wikidata-public-anchor-merge-v1"
    resolution_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_anchors: tuple[AcceptedWikidataAnchor, ...]
    anchor_count: int = Field(ge=0)
    canonical_membership_created: Literal[False] = False
    artist_membership_count: Literal[0] = 0
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _anchor_only(self) -> WikidataPublicAnchorMergeArtifact:
        if self.anchor_count != len(self.public_anchors):
            raise ValueError("anchor count does not match public anchors")
        if any(anchor.confidence != 1.0 for anchor in self.public_anchors):
            raise ValueError("merge accepts only high-confidence exact anchors")
        return self


class WikidataSeedResolutionPublication(_StrictModel):
    """Object-store provenance for all independently published result files."""

    artifact: ObjectWrite
    candidates: ObjectWrite
    accepted: ObjectWrite
    abstentions: ObjectWrite


@dataclass(frozen=True, slots=True)
class _RequestResult:
    response: SparqlResponse
    request_sha256: str
    response_sha256: str
    cache_hit: bool


class WikidataRequestError(RuntimeError):
    """Describe a failed remote request without turning it into an accepted match."""


class _SparqlFetcher(Protocol):
    async def fetch(self, query: str, *, offline: bool) -> _RequestResult:
        """Return one strict response from the cache or Wikidata endpoint."""
        ...


class WikidataSparqlClient:
    """Rate-limited async SPARQL client with deterministic file cache replay."""

    def __init__(self, config: WikidataResolverConfig, cache_directory: Path) -> None:
        """Bind immutable request controls and a local replay cache."""
        self._config = config
        self._cache_directory = cache_directory
        self._next_request_at = 0.0
        self.request_count = 0
        self.cache_hit_count = 0

    @staticmethod
    def _hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _cache_path(self, request_sha256: str) -> Path:
        return self._cache_directory / f"{request_sha256}.json"

    async def fetch(self, query: str, *, offline: bool) -> _RequestResult:
        """Read a verified cache record or issue one bounded network request."""
        request_sha256 = self._hash(query.encode("utf-8"))
        cache_path = self._cache_path(request_sha256)
        if cache_path.is_file():
            try:
                cached = CachedSparqlResponse.model_validate_json(cache_path.read_bytes())
            except (OSError, ValidationError, ValueError) as error:
                raise WikidataRequestError("cached SPARQL response is invalid") from error
            if cached.request_sha256 != request_sha256:
                raise WikidataRequestError("cached SPARQL response does not match its request")
            response_sha256 = self._hash(canonical_json(cached.response))
            if cached.response_sha256 != response_sha256:
                raise WikidataRequestError("cached SPARQL response hash is invalid")
            self.cache_hit_count += 1
            return _RequestResult(cached.response, request_sha256, response_sha256, cache_hit=True)
        if offline:
            raise FileNotFoundError(request_sha256)
        return await self._fetch_network(query, request_sha256, cache_path)

    async def _fetch_network(
        self, query: str, request_sha256: str, cache_path: Path
    ) -> _RequestResult:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + self._config.minimum_request_interval_seconds
            self.request_count += 1
            try:
                async with httpx.AsyncClient(
                    timeout=self._config.request_timeout_seconds,
                    headers={
                        "User-Agent": self._config.user_agent,
                        "Accept": "application/sparql-results+json",
                    },
                    follow_redirects=False,
                ) as client:
                    response = await client.get(
                        _SPARQL_ENDPOINT, params={"format": "json", "query": query}
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    retry_after = response.headers.get("Retry-After")
                    await self._backoff(attempt, retry_after)
                    continue
                response.raise_for_status()
                parsed = SparqlResponse.model_validate(response.json())
            except (httpx.HTTPError, ValidationError, ValueError) as error:
                last_error = error
                if attempt < self._config.max_retries:
                    await self._backoff(attempt, None)
                    continue
                break
            response_sha256 = self._hash(canonical_json(parsed))
            cached = CachedSparqlResponse(
                request_sha256=request_sha256,
                response_sha256=response_sha256,
                response=parsed,
            )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_durable_bytes(cache_path, cached.model_dump_json(indent=2).encode() + b"\n")
            return _RequestResult(parsed, request_sha256, response_sha256, cache_hit=False)
        raise WikidataRequestError(
            "Wikidata SPARQL request failed after bounded retries"
        ) from last_error

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        try:
            requested = float(retry_after) if retry_after is not None else 0.0
        except ValueError:
            requested = 0.0
        await asyncio.sleep(max(requested, float(2**attempt)))


class _GraphNode(_StrictModel):
    source_item_id: str = Field(min_length=1)
    taxonomy_status: str = Field(min_length=1)


class _GraphProjection(_StrictModel):
    seed_input: SeedInput
    nodes: tuple[_GraphNode, ...]


class _TaxonomyInference(_StrictModel):
    source_item_id: str = Field(min_length=1)
    status: str = Field(min_length=1)


class _TaxonomyProjection(_StrictModel):
    seed_input: SeedInput
    inferences: tuple[_TaxonomyInference, ...]


def _projection(path: Path) -> tuple[SeedInput, dict[str, str]]:
    """Parse only names and prior taxonomy states from a committed public artifact."""
    raw = TypeAdapter(dict[str, Any]).validate_json(path.read_bytes())
    if "nodes" in raw:
        document = _GraphProjection.model_validate_json(
            json.dumps(
                {
                    "seed_input": raw.get("seed_input"),
                    "nodes": [
                        {
                            "source_item_id": node.get("source_item_id"),
                            "taxonomy_status": node.get("taxonomy_status"),
                        }
                        if isinstance(node, dict)
                        else node
                        for node in raw.get("nodes", [])
                    ],
                },
                ensure_ascii=False,
            )
        )
        statuses = {node.source_item_id: node.taxonomy_status for node in document.nodes}
        seed = document.seed_input
    elif "inferences" in raw:
        document = _TaxonomyProjection.model_validate_json(
            json.dumps(
                {
                    "seed_input": raw.get("seed_input"),
                    "inferences": [
                        {
                            "source_item_id": inference.get("source_item_id"),
                            "status": inference.get("status"),
                        }
                        if isinstance(inference, dict)
                        else inference
                        for inference in raw.get("inferences", [])
                    ],
                },
                ensure_ascii=False,
            )
        )
        statuses = {item.source_item_id: item.status for item in document.inferences}
        seed = document.seed_input
    else:
        raise ValueError("seed source must be a public taxonomy or open-construction artifact")
    source_ids = {item.source_item_id for item in seed.names}
    if source_ids != set(statuses) or len(statuses) != len(source_ids):
        raise ValueError("seed names and prior taxonomy statuses must cover the same identities")
    return seed, statuses


def _eligible_status(value: str) -> TargetStatus | None:
    """Narrow an untrusted persisted status into the closed eligible subset."""
    match value:
        case "ambiguous_exact":
            return "ambiguous_exact"
        case "ambiguous_compositional":
            return "ambiguous_compositional"
        case "abstained":
            return "abstained"
        case _:
            return None


def select_wikidata_seed_targets(
    source_artifact: Path, config: WikidataResolverConfig
) -> WikidataResolverInput:
    """Select the first lexical batch of unresolved/ambiguous name-only targets."""
    seed, statuses = _projection(source_artifact)
    if len(seed.names) != config.expected_seed_count:
        raise ValueError(
            f"expected {config.expected_seed_count} name seeds, found {len(seed.names)}"
        )
    targets_unsorted: list[WikidataSeedTarget] = []
    for item in seed.names:
        status = _eligible_status(statuses[item.source_item_id])
        if status is not None:
            targets_unsorted.append(
                WikidataSeedTarget(
                    source_item_id=item.source_item_id,
                    source_external_id=item.source_external_id,
                    seed_name=item.name,
                    normalized_name=normalize_label(item.name),
                    prior_status=status,
                )
            )
    targets = tuple(
        sorted(targets_unsorted, key=lambda item: (item.normalized_name, item.source_item_id))
    )
    if not targets:
        raise ValueError("source artifact has no unresolved or ambiguous names")
    return WikidataResolverInput(
        source_artifact_sha256=sha256_file(source_artifact)[0],
        seed_artifact_sha256=seed.artifact_sha256,
        seed_count=len(seed.names),
        eligible_count=len(targets),
        selected_targets=targets[: config.batch_limit],
    )


def _sparql_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _query_for(targets: tuple[WikidataSeedTarget, ...]) -> str:
    values = " ".join(_sparql_literal(target.normalized_name) for target in targets)
    return f"""# Musix Wikidata genre-name resolver; exact normalized English labels/aliases only
SELECT ?term ?item ?label ?matchedName ?matchKind
       (GROUP_CONCAT(DISTINCT STR(?class); separator=\"|\") AS ?classes)
       (GROUP_CONCAT(DISTINCT STR(?parent); separator=\"|\") AS ?parents)
WHERE {{
  VALUES ?term {{ {values} }}
  ?item rdfs:label ?label .
  FILTER(LANG(?label) = \"en\")
  {{
    ?item rdfs:label ?matchedName .
    FILTER(LANG(?matchedName) = \"en\")
    BIND(\"label\" AS ?matchKind)
  }} UNION {{
    ?item skos:altLabel ?matchedName .
    FILTER(LANG(?matchedName) = \"en\")
    BIND(\"alias\" AS ?matchKind)
  }}
  BIND(REPLACE(LCASE(STR(?matchedName)), \"[^\\\\p{{L}}\\\\p{{N}}_]+\", \" \") AS ?normalized)
  FILTER(?normalized = ?term)
  OPTIONAL {{ ?item wdt:P31 ?class . }}
  OPTIONAL {{ ?item wdt:P279 ?parent . }}
}}
GROUP BY ?term ?item ?label ?matchedName ?matchKind
ORDER BY ?term ?item ?matchKind ?matchedName
"""


def _qid(value: str) -> str | None:
    if _QID_PATTERN.search(value) is None:
        return None
    return value.rsplit("/", 1)[-1]


def _binding_value(row: dict[str, SparqlBinding], name: str) -> str | None:
    binding = row.get(name)
    return binding.value if binding is not None else None


def _qid_values(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(sorted({qid for item in value.split("|") if (qid := _qid(item)) is not None}))


def _candidates_from_response(  # noqa: C901
    targets: tuple[WikidataSeedTarget, ...], response: SparqlResponse
) -> tuple[WikidataCandidate, ...]:
    target_by_normalized = {target.normalized_name: target for target in targets}
    grouped: dict[tuple[str, str], list[dict[str, SparqlBinding]]] = defaultdict(list)
    for row in response.results.bindings:
        term = _binding_value(row, "term")
        item = _binding_value(row, "item")
        if term is None or item is None or term not in target_by_normalized:
            continue
        qid = _qid(item)
        label = _binding_value(row, "label")
        matched_name = _binding_value(row, "matchedName")
        match_kind = _binding_value(row, "matchKind")
        if (
            qid is None
            or label is None
            or matched_name is None
            or match_kind not in {"label", "alias"}
            or normalize_label(matched_name) != term
        ):
            continue
        grouped[(term, qid)].append(row)
    candidates: list[WikidataCandidate] = []
    for (term, qid), rows in sorted(grouped.items()):
        target = target_by_normalized[term]
        label_values: set[str] = set()
        matches_values: set[tuple[MatchKind, str]] = set()
        for row in rows:
            label = _binding_value(row, "label")
            if label is not None:
                label_values.add(label)
            matched_name = _binding_value(row, "matchedName")
            match_kind_value = _binding_value(row, "matchKind")
            match match_kind_value:
                case "label":
                    match_kind: MatchKind = "label"
                case "alias":
                    match_kind = "alias"
                case _:
                    continue
            if matched_name is not None:
                matches_values.add((match_kind, matched_name))
        labels = sorted(label_values)
        matches = sorted(matches_values, key=lambda item: (item[0] != "label", item[1]))
        if len(labels) != 1 or not matches:
            continue
        instance_of = _qid_values(_binding_value(rows[0], "classes"))
        subclass_of = _qid_values(_binding_value(rows[0], "parents"))
        match_kind, matched_name = matches[0]
        candidates.append(
            WikidataCandidate(
                source_item_id=target.source_item_id,
                source_external_id=target.source_external_id,
                seed_name=target.seed_name,
                normalized_name=target.normalized_name,
                qid=qid,
                english_label=labels[0],
                matched_english_name=matched_name,
                match_kind=match_kind,
                instance_of_qids=instance_of,
                subclass_of_qids=subclass_of,
                has_direct_music_genre_evidence=(
                    _MUSIC_GENRE_QID in instance_of or _MUSIC_GENRE_QID in subclass_of
                ),
            )
        )
    return tuple(candidates)


def _artifacts_from_candidates(  # noqa: PLR0913
    resolver_input: WikidataResolverInput,
    config: WikidataResolverConfig,
    candidates: tuple[WikidataCandidate, ...],
    *,
    request_plan_sha256: str,
    response_cache_sha256: str,
    runtime: WikidataResolverRuntime,
    request_failures: dict[str, AbstentionReason],
) -> WikidataSeedResolutionArtifact:
    candidate_map: dict[str, list[WikidataCandidate]] = defaultdict(list)
    for candidate in candidates:
        candidate_map[candidate.source_item_id].append(candidate)
    accepted: list[AcceptedWikidataAnchor] = []
    abstentions: list[WikidataAbstention] = []
    for target in resolver_input.selected_targets:
        options = candidate_map[target.source_item_id]
        if target.source_item_id in request_failures:
            reason = request_failures[target.source_item_id]
        elif not options:
            reason = "no_exact_normalized_english_match"
        elif len(options) != 1:
            reason = "ambiguous_exact_wikidata_candidates"
        elif not options[0].has_direct_music_genre_evidence:
            reason = "unique_exact_match_lacks_music_genre_evidence"
        else:
            option = options[0]
            accepted.append(
                AcceptedWikidataAnchor(
                    source_item_id=option.source_item_id,
                    source_external_id=option.source_external_id,
                    seed_name=option.seed_name,
                    normalized_name=option.normalized_name,
                    wikidata_qid=option.qid,
                    english_label=option.english_label,
                    matched_english_name=option.matched_english_name,
                    match_kind=option.match_kind,
                )
            )
            continue
        abstentions.append(
            WikidataAbstention(
                source_item_id=target.source_item_id,
                source_external_id=target.source_external_id,
                seed_name=target.seed_name,
                normalized_name=target.normalized_name,
                reason=reason,
                candidate_qids=tuple(sorted(option.qid for option in options)),
            )
        )
    counts = WikidataResolverCounts(
        targets=len(resolver_input.selected_targets),
        candidate_count=len(candidates),
        accepted_exact_unique_count=len(accepted),
        abstention_count=len(abstentions),
        ambiguity_count=sum(
            item.reason == "ambiguous_exact_wikidata_candidates" for item in abstentions
        ),
        offline_cache_miss_count=sum(item.reason == "offline_cache_miss" for item in abstentions),
        request_failure_count=sum(item.reason == "wikidata_request_failed" for item in abstentions),
    )
    preliminary = WikidataSeedResolutionArtifact(
        input=resolver_input,
        config=config,
        request_plan_sha256=request_plan_sha256,
        response_cache_sha256=response_cache_sha256,
        candidates=candidates,
        accepted_exact_unique=tuple(accepted),
        abstentions=tuple(abstentions),
        counts=counts,
        runtime=runtime,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": _logical_hash(preliminary)})


def _logical_hash(artifact: WikidataSeedResolutionArtifact) -> str:
    document = artifact.model_dump(mode="json", exclude={"output_sha256", "runtime"})
    payload = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


async def resolve_wikidata_seed_batch(
    source_artifact: Path,
    *,
    config: WikidataResolverConfig,
    cache_directory: Path,
    offline: bool = False,
    fetcher: _SparqlFetcher | None = None,
) -> WikidataSeedResolutionArtifact:
    """Resolve one bounded deterministic batch, retaining all ambiguity and failures."""
    started = time.monotonic()
    resolver_input = select_wikidata_seed_targets(source_artifact, config)
    client = fetcher or WikidataSparqlClient(config, cache_directory)
    candidates: list[WikidataCandidate] = []
    request_hashes: list[str] = []
    response_hashes: list[str] = []
    failures: dict[str, AbstentionReason] = {}
    targets = resolver_input.selected_targets
    for offset in range(0, len(targets), config.sparql_terms_per_request):
        group = targets[offset : offset + config.sparql_terms_per_request]
        query = _query_for(group)
        request_hash = hashlib.sha256(query.encode()).hexdigest()
        request_hashes.append(request_hash)
        try:
            result = await client.fetch(query, offline=offline)
        except FileNotFoundError:
            failures.update({target.source_item_id: "offline_cache_miss" for target in group})
            continue
        except WikidataRequestError:
            failures.update({target.source_item_id: "wikidata_request_failed" for target in group})
            continue
        if result.request_sha256 != request_hash:
            failures.update({target.source_item_id: "wikidata_request_failed" for target in group})
            continue
        response_hashes.append(result.response_sha256)
        candidates.extend(_candidates_from_response(group, result.response))
    request_count = (
        client.request_count if isinstance(client, WikidataSparqlClient) else len(request_hashes)
    )
    cache_hits = client.cache_hit_count if isinstance(client, WikidataSparqlClient) else 0
    return _artifacts_from_candidates(
        resolver_input,
        config,
        tuple(sorted(candidates, key=lambda item: (item.source_item_id, item.qid))),
        request_plan_sha256=hashlib.sha256("\n".join(request_hashes).encode()).hexdigest(),
        response_cache_sha256=hashlib.sha256("\n".join(response_hashes).encode()).hexdigest(),
        runtime=WikidataResolverRuntime(
            elapsed_seconds=round(time.monotonic() - started, 6),
            request_count=request_count,
            cache_hit_count=cache_hits,
            offline_replay=offline,
        ),
        request_failures=failures,
    )


def write_wikidata_seed_resolution(
    artifact: WikidataSeedResolutionArtifact, output: Path
) -> tuple[Path, Path, Path, Path]:
    """Write resolver, candidates, accepted, and abstentions as four separate JSON artifacts."""
    if artifact.output_sha256 != _logical_hash(artifact):
        raise ValueError("Wikidata resolver artifact logical hash does not match content")
    candidates = output.with_name(f"{output.stem}.candidates.json")
    accepted = output.with_name(f"{output.stem}.accepted.json")
    abstentions = output.with_name(f"{output.stem}.abstentions.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(output, artifact.model_dump_json(indent=2).encode() + b"\n")
    candidates.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(
        candidates,
        json.dumps(
            [item.model_dump(mode="json") for item in artifact.candidates], indent=2, sort_keys=True
        ).encode()
        + b"\n",
    )
    accepted.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(
        accepted,
        json.dumps(
            [item.model_dump(mode="json") for item in artifact.accepted_exact_unique],
            indent=2,
            sort_keys=True,
        ).encode()
        + b"\n",
    )
    abstentions.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(
        abstentions,
        json.dumps(
            [item.model_dump(mode="json") for item in artifact.abstentions],
            indent=2,
            sort_keys=True,
        ).encode()
        + b"\n",
    )
    return output, candidates, accepted, abstentions


def publish_wikidata_seed_resolution(
    artifact: WikidataSeedResolutionArtifact, *, output: Path, store: ObjectStore
) -> WikidataSeedResolutionPublication:
    """Publish every result stream under immutable content-addressed ObjectStore keys."""
    main, candidates, accepted, abstentions = write_wikidata_seed_resolution(artifact, output)
    files = (main, candidates, accepted, abstentions)
    writes: list[ObjectWrite] = []
    for path in files:
        digest = sha256_file(path)[0]
        write = store.push(path, ObjectKey(value=f"wikidata-seed-resolution/{digest}/{path.name}"))
        if write.sha256 != digest:
            raise ValueError("object store changed Wikidata resolver artifact")
        writes.append(write)
    return WikidataSeedResolutionPublication(
        artifact=writes[0], candidates=writes[1], accepted=writes[2], abstentions=writes[3]
    )


def merge_wikidata_public_anchors(
    resolution_artifact_path: Path,
) -> WikidataPublicAnchorMergeArtifact:
    """Create an anchor-only public merge input from a verified resolver artifact."""
    payload = resolution_artifact_path.read_bytes()
    try:
        resolution = WikidataSeedResolutionArtifact.model_validate_json(payload)
    except (ValidationError, ValueError) as error:
        raise ValueError("Wikidata resolver artifact is invalid") from error
    if resolution.output_sha256 != _logical_hash(resolution):
        raise ValueError("Wikidata resolver artifact logical hash is invalid")
    preliminary = WikidataPublicAnchorMergeArtifact(
        resolution_output_sha256=resolution.output_sha256,
        resolution_artifact_sha256=hashlib.sha256(payload).hexdigest(),
        public_anchors=resolution.accepted_exact_unique,
        anchor_count=len(resolution.accepted_exact_unique),
        output_sha256="0" * 64,
    )
    digest = hashlib.sha256(
        json.dumps(
            preliminary.model_dump(mode="json", exclude={"output_sha256"}),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return preliminary.model_copy(update={"output_sha256": digest})


def write_wikidata_public_anchor_merge(
    artifact: WikidataPublicAnchorMergeArtifact, output: Path
) -> tuple[str, int]:
    """Write one typed, no-membership merge projection."""
    expected = hashlib.sha256(
        json.dumps(
            artifact.model_dump(mode="json", exclude={"output_sha256"}),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if artifact.output_sha256 != expected:
        raise ValueError("Wikidata public anchor merge hash is invalid")
    payload = artifact.model_dump_json(indent=2).encode() + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(output, payload)
    return sha256_hex(payload), len(payload)
