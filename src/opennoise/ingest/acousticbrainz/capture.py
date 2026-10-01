"""Bounded metadata capture and complete network-free replay of exact recording evidence."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

import httpx
from pydantic import BaseModel, TypeAdapter

from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_hex, sha256_json
from opennoise.ingest.acousticbrainz.models import (
    ACOUSTICBRAINZ_ORIGIN,
    MAX_API_REQUESTS,
    MAX_ARTISTS,
    MAX_RESPONSE_BYTES,
    MAX_RIGHTS_REQUESTS,
    MAX_TOTAL_BYTES,
    MUSICBRAINZ_ORIGIN,
    RECORDINGS_PER_ARTIST,
    REVISION,
    RIGHTS_URL,
    SEARCH_LIMIT,
    USER_AGENT,
    ArtistCoverage,
    BenchmarkArtist,
    BenchmarkSummary,
    FeatureOutcome,
    QueryManifest,
    SourceCapture,
)
from opennoise.ingest.acousticbrainz.projection import (
    NUMERIC_PATHS,
    AcousticIdentityError,
    json_document,
    project_high_level,
    project_low_level,
    select_recordings,
    verify_embedded_recording,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

RATE_INTERVAL = 1.1
HEADER_NAMES = frozenset(
    {
        "content-type",
        "content-length",
        "content-encoding",
        "date",
        "etag",
        "last-modified",
        "cache-control",
        "server",
        "vary",
        "location",
    }
)
POLICY = {
    "revision": REVISION,
    "scope": "local_research_only",
    "metadata_only": True,
    "audio_requested": False,
    "model_input_allowed": False,
    "product_promotion_allowed": False,
    "names_used_for_identity": False,
    "alias_merging_allowed": False,
    "source_license": "CC0-1.0",
    "high_level_role": "derived_unvalidated_acoustic_model_output",
    "representative_sample": False,
    "source_audio_analysis_preexisting": True,
    "calibrated": False,
    "http_redirects_followed": False,
    "retries_per_request": 0,
}


def search_url(artist: UUID) -> str:
    """Use the exact artist ID query without any name search or relation expansion."""
    return str(
        httpx.URL(
            MUSICBRAINZ_ORIGIN + "/ws/2/recording",
            params={"query": f"arid:{artist}", "limit": SEARCH_LIMIT, "fmt": "json"},
        )
    )


def feature_url(recording: UUID, level: Literal["high-level", "low-level"]) -> str:
    """Only the two fixed metadata endpoints can be requested for exact recordings."""
    return f"{ACOUSTICBRAINZ_ORIGIN}/api/v1/{recording}/{level}"


def _write_json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")


def _dump(model: BaseModel) -> dict[str, object]:
    return cast("dict[str, object]", model.model_dump(mode="json"))


def _payload(directory: Path, source: SourceCapture) -> bytes:
    return (directory / source.payload_path).read_bytes()


def _inventory(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): sha256_file(path)[0]
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _cohort(source: Path) -> tuple[BenchmarkArtist, ...]:
    rows = TypeAdapter(list[dict[str, object]]).validate_python(
        json_document(source.read_bytes())["benchmark_artists"]
    )
    artists = tuple(
        sorted(
            (
                BenchmarkArtist(artist_mbid=UUID(str(row["artist_mbid"])), name=str(row["name"]))
                for row in rows
            ),
            key=lambda artist: str(artist.artist_mbid),
        )
    )
    if len(artists) != MAX_ARTISTS or len({row.artist_mbid for row in artists}) != MAX_ARTISTS:
        raise ValueError("benchmark capture requires ten distinct exact cohort artist UUIDs")
    return artists


def _verify_rights(capture: SourceCapture, payload: bytes) -> None:
    if (
        capture.kind != "rights"
        or capture.requested_url != RIGHTS_URL
        or capture.status_code != HTTPStatus.OK
        or not capture.payload_complete
        or capture.error_kind
        or b"CC0" not in payload
        or b"AcousticBrainz" not in payload
    ):
        raise ValueError("official complete AcousticBrainz rights page does not establish CC0")


class BoundedCapture:
    """One sequential request plan with a shared byte and request budget, without retries."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        directory: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Use a caller-owned HTTP client, inherited proxy/TLS trust, and fixed endpoints."""
        self.client = client
        self.directory = directory
        self.clock = clock
        self.sleep = sleep
        self.next_request_at = 0.0
        self.api_request_count = 0
        self.rights_request_count = 0
        self.retained_bytes = 0
        self.captures: list[SourceCapture] = []

    async def fetch(
        self,
        *,
        kind: Literal["rights", "search", "high-level", "low-level"],
        artist: UUID | None = None,
        recording: UUID | None = None,
    ) -> SourceCapture:
        """Save complete bounded bytes, or an explicit bounded partial/failure response."""
        if kind == "rights":
            if (
                artist is not None
                or recording is not None
                or self.rights_request_count >= MAX_RIGHTS_REQUESTS
            ):
                raise ValueError("rights request exceeds exact source plan")
            url = RIGHTS_URL
            self.rights_request_count += 1
        else:
            if self.api_request_count >= MAX_API_REQUESTS:
                raise ValueError("API request budget exhausted")
            if artist is None or (kind != "search" and recording is None):
                raise ValueError("API request requires exact source identities")
            url = (
                search_url(artist)
                if kind == "search"
                else feature_url(cast("UUID", recording), kind)
            )
            self.api_request_count += 1
        if self.retained_bytes >= MAX_TOTAL_BYTES:
            raise ValueError("response byte budget exhausted before request")
        await self.sleep(max(0.0, self.next_request_at - self.clock()))
        self.next_request_at = self.clock() + RATE_INTERVAL
        fetched_at = datetime.now(UTC).isoformat()
        index = len(self.captures) + 1
        status_code, error_kind = None, None
        headers: dict[str, str] = {}
        payload = bytearray()
        complete = False
        limit = min(MAX_RESPONSE_BYTES, MAX_TOTAL_BYTES - self.retained_bytes)
        try:
            async with self.client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html" if kind == "rights" else "application/json",
                    "Accept-Encoding": "identity",
                },
                follow_redirects=False,
            ) as response:
                status_code = response.status_code
                headers = {
                    key: value for key, value in response.headers.items() if key in HEADER_NAMES
                }
                if headers.get("content-type", "").startswith("audio/"):
                    error_kind = "unexpected_media_type"
                else:
                    async for chunk in response.aiter_bytes(chunk_size=16_384):
                        remaining = limit - len(payload)
                        payload.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            error_kind = "response_byte_bound"
                            break
                    else:
                        complete = True
        except httpx.HTTPError:
            error_kind = "transport_error"
        path = f"raw/{index:03d}.bin"
        with (self.directory / path).open("xb") as stream:
            stream.write(payload)
        self.retained_bytes += len(payload)
        source = SourceCapture(
            request_index=index,
            kind=kind,
            requested_url=url,
            fetched_at=fetched_at,
            artist_mbid=artist,
            recording_mbid=recording,
            status_code=status_code,
            response_headers=headers,
            payload_path=path,
            payload_sha256=sha256_hex(bytes(payload)),
            payload_bytes=len(payload),
            payload_complete=complete,
            error_kind=error_kind,
        )
        self.captures.append(source)
        return source


def _outcome(  # noqa: PLR0911, PLR0913 - preserve explicit identity, schema and failure inputs.
    source: SourceCapture | None,
    payload: bytes,
    *,
    artist: UUID,
    recording: UUID,
    level: Literal["high-level", "low-level"],
    projection_revision: Literal["v1", "v2"] = "v1",
) -> FeatureOutcome:
    base = FeatureOutcome(
        artist_mbid=artist,
        recording_mbid=recording,
        level=level,
        request_index=source.request_index if source else None,
        state="not_requested_byte_budget",
        embedded_identity="not_checked",
    )
    if source is None:
        return base
    if source.error_kind or not source.payload_complete:
        return base.model_copy(update={"state": "request_failed"})
    if source.status_code == HTTPStatus.NOT_FOUND:
        return base.model_copy(update={"state": "missing_http_404"})
    if source.status_code != HTTPStatus.OK:
        return base.model_copy(update={"state": "http_error"})
    try:
        document = json_document(payload)
        identity = verify_embedded_recording(document, recording)
        numeric = (
            project_low_level(document, revision=projection_revision)
            if level == "low-level"
            else ()
        )
        models = project_high_level(document) if level == "high-level" else ()
    except AcousticIdentityError:
        return base.model_copy(update={"state": "review_identity_mismatch"})
    except (ValueError, KeyError, RecursionError):
        return base.model_copy(update={"state": "review_invalid_schema"})
    return base.model_copy(
        update={
            "state": "available",
            "embedded_identity": identity,
            "numeric_descriptors": numeric,
            "high_level_models": models,
        }
    )


def _summary(
    manifest: QueryManifest,
    captures: Sequence[SourceCapture],
    directory: Path,
    *,
    projection_revision: Literal["v1", "v2"] = "v1",
) -> BenchmarkSummary:
    features = {
        (source.artist_mbid, source.recording_mbid, source.kind): source
        for source in captures
        if source.kind in {"high-level", "low-level"}
    }
    outcomes = []
    for row in manifest.recordings:
        for level in ("high-level", "low-level"):
            source = features.get((row.artist_mbid, row.recording_mbid, level))
            outcomes.append(
                _outcome(
                    source,
                    (directory / source.payload_path).read_bytes() if source else b"",
                    artist=row.artist_mbid,
                    recording=row.recording_mbid,
                    level=level,
                    projection_revision=projection_revision,
                )
            )
    artists = tuple(
        ArtistCoverage(
            artist_mbid=artist.artist_mbid,
            name=artist.name,
            selected_recordings=sum(
                row.artist_mbid == artist.artist_mbid for row in manifest.recordings
            ),
            high_level_state_counts=dict(
                Counter(
                    row.state
                    for row in outcomes
                    if row.artist_mbid == artist.artist_mbid and row.level == "high-level"
                )
            ),
            low_level_state_counts=dict(
                Counter(
                    row.state
                    for row in outcomes
                    if row.artist_mbid == artist.artist_mbid and row.level == "low-level"
                )
            ),
        )
        for artist in manifest.artists
    )
    return BenchmarkSummary(
        numeric_projection_revision=projection_revision,
        manifest_sha256=sha256_file(directory / "query-manifest.json")[0],
        selected_recording_count=len(manifest.recordings),
        api_request_count=sum(source.kind != "rights" for source in captures),
        rights_request_count=sum(source.kind == "rights" for source in captures),
        retained_response_bytes=sum(source.payload_bytes for source in captures),
        state_counts={
            level: dict(Counter(row.state for row in outcomes if row.level == level))
            for level in ("high-level", "low-level")
        },
        numeric_descriptor_available_counts=dict(
            Counter(
                descriptor.path
                for row in outcomes
                for descriptor in row.numeric_descriptors
                if descriptor.value is not None
            )
        ),
        artists=artists,
        outcomes=tuple(outcomes),
    )


def _prepare(
    benchmark_source: Path, directory: Path
) -> tuple[tuple[BenchmarkArtist, ...], dict[str, dict[str, str]], dict[str, object]]:
    """Pin source cohort, policy and implementation before any network requests."""
    require_local_candidate_destination(directory)
    if directory.exists() or directory.is_symlink():
        raise FileExistsError("refusing to overwrite AcousticBrainz benchmark capture")
    artists = _cohort(benchmark_source)
    directory.mkdir(parents=True)
    (directory / "raw").mkdir()
    code = directory / "frozen-code"
    code.mkdir()
    project = Path(__file__).resolve().parents[4]
    paths = (
        *sorted(Path(__file__).parent.glob("*.py")),
        project / "scripts/capture_acousticbrainz_benchmarks.py",
    )
    bindings = {}
    for path in paths:
        snapshot = code / path.name
        snapshot.write_bytes(path.read_bytes())
        bindings[str(path.relative_to(project))] = {
            "sha256": sha256_file(snapshot)[0],
            "snapshot": str(snapshot.relative_to(directory)),
        }
    (directory / "benchmark-source.json").write_bytes(benchmark_source.read_bytes())
    declaration = {
        "policy": POLICY,
        "benchmark_source_sha256": sha256_file(benchmark_source)[0],
        "artists": [_dump(artist) for artist in artists],
        "search_limit_per_artist": SEARCH_LIMIT,
        "recordings_per_artist": RECORDINGS_PER_ARTIST,
        "selection": "first_three_uuid_sorted_exact_credits_within_first_search_25",
        "levels": ["high-level", "low-level"],
        "numeric_projection_revision": "v2",
        "numeric_projection_paths": NUMERIC_PATHS,
        "maximum_api_requests": MAX_API_REQUESTS,
        "maximum_rights_requests": MAX_RIGHTS_REQUESTS,
        "maximum_response_bytes": MAX_RESPONSE_BYTES,
        "maximum_total_response_bytes": MAX_TOTAL_BYTES,
        "minimum_request_interval_seconds": RATE_INTERVAL,
        "user_agent": USER_AGENT,
        "response_headers_retained": sorted(HEADER_NAMES),
        "implementation_bindings": bindings,
    }
    _write_json(directory / "pre-capture-declaration.json", declaration)
    return artists, bindings, declaration


def _current_implementation_matches(bindings: dict[str, dict[str, str]]) -> bool:
    project = Path(__file__).resolve().parents[4]
    return all(
        sha256_file(project / path)[0] == binding["sha256"] for path, binding in bindings.items()
    )


async def capture_benchmarks(
    *, benchmark_source: Path, directory: Path, client: httpx.AsyncClient
) -> dict[str, object]:
    """Capture once into a fresh cache; completed captures have a separate offline replay."""
    artists, bindings, declaration = _prepare(benchmark_source, directory)
    fetcher = BoundedCapture(client, directory)
    rights = await fetcher.fetch(kind="rights")
    _verify_rights(rights, _payload(directory, rights))
    searches, recordings = [], []
    for artist in artists:
        source = await fetcher.fetch(kind="search", artist=artist.artist_mbid)
        selection, chosen = select_recordings(source, _payload(directory, source))
        searches.append(selection)
        recordings.extend(chosen)
    _write_json(
        directory / "selection-source-captures.json", [_dump(source) for source in fetcher.captures]
    )
    manifest = QueryManifest(
        benchmark_source_sha256=cast("str", declaration["benchmark_source_sha256"]),
        declaration_sha256=sha256_file(directory / "pre-capture-declaration.json")[0],
        rights_capture_sha256=rights.payload_sha256,
        artist_search_captures_sha256=sha256_file(directory / "selection-source-captures.json")[0],
        artists=artists,
        searches=tuple(searches),
        recordings=tuple(recordings),
    )
    _write_json(directory / "query-manifest.json", _dump(manifest))
    # Recording IDs and exact source credits are immutable before any feature call.
    manifest_digest = sha256_file(directory / "query-manifest.json")[0]
    for row in recordings:
        for level in ("high-level", "low-level"):
            if fetcher.retained_bytes < MAX_TOTAL_BYTES:
                await fetcher.fetch(
                    kind=level, artist=row.artist_mbid, recording=row.recording_mbid
                )
    _write_json(directory / "source-captures.json", [_dump(source) for source in fetcher.captures])
    if manifest_digest != sha256_file(directory / "query-manifest.json")[
        0
    ] or not _current_implementation_matches(bindings):
        raise ValueError("frozen selection or implementation changed during metadata capture")
    summary = _summary(manifest, fetcher.captures, directory, projection_revision="v2")
    _write_json(directory / "summary.json", _dump(summary))
    receipt: dict[str, object] = {
        "policy": POLICY,
        "manifest_sha256": manifest_digest,
        "api_request_count": summary.api_request_count,
        "rights_request_count": summary.rights_request_count,
        "retained_response_bytes": summary.retained_response_bytes,
        "implementation_bindings": bindings,
        "files": _inventory(directory),
    }
    receipt["output_sha256"] = sha256_json(receipt)
    _write_json(directory / "receipt.json", receipt)
    return verify_benchmarks(directory=directory)


def verify_benchmarks(*, directory: Path) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915 - full offline provenance and projection replay.
    """Replay capture bytes, exact credit selection, request bounds and projections offline."""
    require_local_candidate_destination(directory)
    receipt = json_document((directory / "receipt.json").read_bytes())
    if receipt.get("policy") != POLICY or receipt.get("output_sha256") != sha256_json(
        {key: value for key, value in receipt.items() if key != "output_sha256"}
    ):
        raise ValueError("AcousticBrainz receipt policy or self identity differs")
    files = TypeAdapter(dict[str, str]).validate_python(receipt["files"])
    actual_files = {
        str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()
    } - {"receipt.json"}
    if set(files) != actual_files:
        raise ValueError("AcousticBrainz captured file inventory differs")
    for name, digest in files.items():
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or (directory / path).is_symlink()
            or sha256_file(directory / path)[0] != digest
        ):
            raise ValueError("AcousticBrainz captured file hash differs")
    captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (directory / "source-captures.json").read_bytes()
    )
    declaration = json_document((directory / "pre-capture-declaration.json").read_bytes())
    manifest = QueryManifest.model_validate_json((directory / "query-manifest.json").read_bytes())
    if (
        declaration.get("policy") != POLICY
        or manifest.artists != _cohort(directory / "benchmark-source.json")
        or manifest.benchmark_source_sha256 != sha256_file(directory / "benchmark-source.json")[0]
        or manifest.declaration_sha256 != sha256_file(directory / "pre-capture-declaration.json")[0]
        or manifest.artist_search_captures_sha256
        != sha256_file(directory / "selection-source-captures.json")[0]
    ):
        raise ValueError("frozen source cohort or selection bindings differ")
    if receipt["manifest_sha256"] != sha256_file(directory / "query-manifest.json")[0]:
        raise ValueError("query manifest identity differs")
    selection_captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (directory / "selection-source-captures.json").read_bytes()
    )
    if (
        selection_captures != captures[: MAX_ARTISTS + MAX_RIGHTS_REQUESTS]
        or not captures
        or captures[0].kind != "rights"
    ):
        raise ValueError("source selection was not frozen before acoustic feature requests")
    expected_searches, expected_recordings = [], []
    expected_api_count = sum(source.kind != "rights" for source in captures)
    if (
        expected_api_count > MAX_API_REQUESTS
        or sum(source.kind == "rights" for source in captures) != MAX_RIGHTS_REQUESTS
    ):
        raise ValueError("source request bounds differ")
    for index, source in enumerate(captures, 1):
        if source.request_index != index or source.payload_path != f"raw/{index:03d}.bin":
            raise ValueError("source request order or raw path differs")
        payload = (directory / source.payload_path).read_bytes()
        if sha256_hex(payload) != source.payload_sha256 or len(payload) != source.payload_bytes:
            raise ValueError("source response bytes differ")
        expected_url = (
            RIGHTS_URL
            if source.kind == "rights"
            else search_url(cast("UUID", source.artist_mbid))
            if source.kind == "search"
            else feature_url(cast("UUID", source.recording_mbid), source.kind)
        )
        if source.requested_url != expected_url:
            raise ValueError("source endpoint or exact recording identity differs")
        if source.kind == "rights":
            _verify_rights(source, payload)
            if source.payload_sha256 != manifest.rights_capture_sha256:
                raise ValueError("official rights capture identity differs")
        elif source.kind == "search":
            expected_artist = manifest.artists[index - 2].artist_mbid
            if source.artist_mbid != expected_artist or source.recording_mbid is not None:
                raise ValueError("artist search plan differs from exact source cohort")
            selection, chosen = select_recordings(source, payload)
            expected_searches.append(selection)
            expected_recordings.extend(chosen)
    if (
        tuple(expected_searches) != manifest.searches
        or tuple(expected_recordings) != manifest.recordings
    ):
        raise ValueError("exact artist-credit recording selection did not replay")
    feature_plan = [
        (row.artist_mbid, row.recording_mbid, level)
        for row in manifest.recordings
        for level in ("high-level", "low-level")
    ]
    actual_plan = [
        (source.artist_mbid, source.recording_mbid, source.kind)
        for source in captures[MAX_ARTISTS + MAX_RIGHTS_REQUESTS :]
    ]
    if actual_plan != feature_plan[: len(actual_plan)] or (
        len(actual_plan) != len(feature_plan)
        and sum(source.payload_bytes for source in captures) != MAX_TOTAL_BYTES
    ):
        raise ValueError("feature request plan or byte-budget abstention differs")
    bindings = TypeAdapter(dict[str, dict[str, str]]).validate_python(
        receipt["implementation_bindings"]
    )
    if bindings != declaration.get("implementation_bindings") or any(
        Path(binding["snapshot"]).is_absolute()
        or ".." in Path(binding["snapshot"]).parts
        or sha256_file(directory / binding["snapshot"])[0] != binding["sha256"]
        for binding in bindings.values()
    ):
        raise ValueError("frozen implementation identities differ")
    projection_revision = TypeAdapter(Literal["v1", "v2"]).validate_python(
        declaration.get("numeric_projection_revision", "v1")
    )
    expected_summary = _summary(
        manifest, captures, directory, projection_revision=projection_revision
    )
    retained_summary = BenchmarkSummary.model_validate_json(
        (directory / "summary.json").read_bytes()
    )
    if expected_summary != retained_summary or any(
        receipt[key] != getattr(expected_summary, key)
        for key in ("api_request_count", "rights_request_count", "retained_response_bytes")
    ):
        raise ValueError("offline metadata projection or capture totals did not replay")
    return {
        "output_sha256": receipt["output_sha256"],
        "offline_replay_verified": True,
        "selected_recording_count": expected_summary.selected_recording_count,
        "api_request_count": expected_summary.api_request_count,
        "rights_request_count": expected_summary.rights_request_count,
        "retained_response_bytes": expected_summary.retained_response_bytes,
        "state_counts": expected_summary.state_counts,
        "numeric_descriptor_available_counts": expected_summary.numeric_descriptor_available_counts,
        "audio_requested": False,
        "model_input_allowed": False,
        "product_promotion_allowed": False,
    }


def reproject_benchmarks(*, source_directory: Path, directory: Path) -> dict[str, object]:
    """Freeze a corrected scalar-statistic projection of existing bytes, with zero HTTP requests."""
    source = verify_benchmarks(directory=source_directory)
    artists, bindings, _ = _prepare(source_directory / "benchmark-source.json", directory)
    declaration = {
        "revision": "acousticbrainz-benchmark-offline-numeric-projection-v2",
        "source_directory": str(source_directory.resolve()),
        "source_capture_output_sha256": source["output_sha256"],
        "source_receipt_sha256": sha256_file(source_directory / "receipt.json")[0],
        "source_manifest_sha256": sha256_file(source_directory / "query-manifest.json")[0],
        "numeric_projection_paths": NUMERIC_PATHS,
        "numeric_projection_revision": "v2",
        "schema_correction": (
            "BPM histogram peak fields are statistics objects; retain their mean subfields"
        ),
        "source_recordings_and_selection_unchanged": True,
        "new_upstream_requests": 0,
        "implementation_bindings": bindings,
    }
    _write_json(directory / "pre-reprojection-declaration.json", declaration)
    manifest = QueryManifest.model_validate_json(
        (source_directory / "query-manifest.json").read_bytes()
    )
    captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (source_directory / "source-captures.json").read_bytes()
    )
    if manifest.artists != artists:
        raise ValueError("offline reprojection cohort differs from captured source")
    summary = _summary(manifest, captures, source_directory, projection_revision="v2")
    _write_json(directory / "summary.json", _dump(summary))
    if not _current_implementation_matches(bindings):
        raise ValueError("offline reprojection implementation changed while frozen")
    receipt: dict[str, object] = {
        "policy": POLICY,
        "revision": declaration["revision"],
        "source_capture_output_sha256": source["output_sha256"],
        "new_upstream_requests": 0,
        "implementation_bindings": bindings,
        "files": _inventory(directory),
    }
    receipt["output_sha256"] = sha256_json(receipt)
    _write_json(directory / "receipt.json", receipt)
    return verify_reprojection(directory=directory)


def verify_reprojection(*, directory: Path) -> dict[str, object]:
    """Replay the corrected projection from bound source captures, entirely offline."""
    require_local_candidate_destination(directory)
    receipt = json_document((directory / "receipt.json").read_bytes())
    if (
        receipt.get("policy") != POLICY
        or receipt.get("new_upstream_requests") != 0
        or receipt.get("output_sha256")
        != sha256_json({key: value for key, value in receipt.items() if key != "output_sha256"})
    ):
        raise ValueError("offline reprojection policy or self identity differs")
    inventory = _inventory(directory)
    inventory.pop("receipt.json")
    if receipt.get("files") != inventory:
        raise ValueError("offline reprojection file inventory or hashes differ")
    declaration = json_document((directory / "pre-reprojection-declaration.json").read_bytes())
    if (
        declaration.get("numeric_projection_paths") != list(NUMERIC_PATHS)
        or declaration.get("numeric_projection_revision") != "v2"
        or declaration.get("new_upstream_requests") != 0
    ):
        raise ValueError("offline numeric projection schema differs")
    source_directory = Path(str(declaration["source_directory"]))
    source = verify_benchmarks(directory=source_directory)
    if (
        source["output_sha256"] != declaration["source_capture_output_sha256"]
        or receipt["source_capture_output_sha256"] != source["output_sha256"]
        or declaration["source_receipt_sha256"] != sha256_file(source_directory / "receipt.json")[0]
        or declaration["source_manifest_sha256"]
        != sha256_file(source_directory / "query-manifest.json")[0]
    ):
        raise ValueError("offline projection source capture binding differs")
    bindings = TypeAdapter(dict[str, dict[str, str]]).validate_python(
        receipt["implementation_bindings"]
    )
    if bindings != declaration.get("implementation_bindings") or any(
        Path(binding["snapshot"]).is_absolute()
        or ".." in Path(binding["snapshot"]).parts
        or sha256_file(directory / binding["snapshot"])[0] != binding["sha256"]
        for binding in bindings.values()
    ):
        raise ValueError("offline projection frozen implementation differs")
    manifest = QueryManifest.model_validate_json(
        (source_directory / "query-manifest.json").read_bytes()
    )
    captures = TypeAdapter(tuple[SourceCapture, ...]).validate_json(
        (source_directory / "source-captures.json").read_bytes()
    )
    expected = _summary(manifest, captures, source_directory, projection_revision="v2")
    retained = BenchmarkSummary.model_validate_json((directory / "summary.json").read_bytes())
    if expected != retained:
        raise ValueError("offline corrected descriptor projection did not replay")
    return {
        "output_sha256": receipt["output_sha256"],
        "source_capture_output_sha256": source["output_sha256"],
        "offline_replay_verified": True,
        "new_upstream_requests": 0,
        "selected_recording_count": retained.selected_recording_count,
        "source_api_request_count": retained.api_request_count,
        "source_rights_request_count": retained.rights_request_count,
        "retained_source_response_bytes": retained.retained_response_bytes,
        "state_counts": retained.state_counts,
        "numeric_descriptor_available_counts": retained.numeric_descriptor_available_counts,
        "audio_requested": False,
        "model_input_allowed": False,
        "product_promotion_allowed": False,
    }
