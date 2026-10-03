"""Optional exact recording destinations and separately attributed FMA track context."""

from __future__ import annotations

import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zstandard

from opennoise.common import sha256_file
from opennoise.deployment.fma_static import refresh_fma_static_display
from opennoise.ingest.fma.corpus import project_corpus
from opennoise.ingest.wikidata.genre_context import verify_pack as verify_genre_context_pack
from opennoise.serving.metadata.fma_identity_bridge import verify_fma_exact_bridge
from opennoise.serving.metadata.fma_listening import export_fma_listening, verify_fma_listening_pack
from opennoise.serving.metadata.listening_destinations import verify_recording_listening_pack


@dataclass(frozen=True)
class FullInputSources:
    """Explicit optional input roles keep source licenses and entity namespaces distinct."""

    entity_pack: Path | None = None
    listening_pack: Path | None = None
    fma_source: Path | None = None
    fma_projection: Path | None = None
    fma_bridge: Path | None = None
    fma_static: Path | None = None
    fma_listening_pack: Path | None = None
    genre_context_pack: Path | None = None
    fma_map: Path | None = None
    fma_memberships: Path | None = None
    artist_source_completion: Path | None = None

    def bindings(self) -> dict[str, str | None]:
        """Bind replayable inputs by exact files without inventing source transport facts."""
        roles = {
            "entity_pack": (self.entity_pack, "receipt.json"),
            "listening_pack": (self.listening_pack, "receipt.json"),
            "fma_source": (self.fma_source, "source-receipt.json"),
            "fma_projection": (self.fma_projection, "corpus-receipt.json"),
            "fma_bridge": (self.fma_bridge, "receipt.json"),
            "fma_static": (self.fma_static, "static-receipt.json"),
            "fma_listening_pack": (self.fma_listening_pack, "listening.json"),
            "genre_context_pack": (self.genre_context_pack, "receipt.json"),
            "fma_map": (self.fma_map, "receipt.json"),
            "fma_memberships": (self.fma_memberships, "pack-receipt.json"),
            "artist_source_completion": (self.artist_source_completion, "receipt.json"),
        }
        return {
            role: sha256_file(directory / name)[0] if directory else None
            for role, (directory, name) in roles.items()
        }


def add_recording_destinations(root: Path, artists: dict[str, dict[str, Any]], pack: Path) -> None:
    """Attach replayed provider facts only to the same native recording and artist IDs."""
    projection = verify_recording_listening_pack(pack, root / "data/examples/recording-facts")
    for row in projection["recordings"]:
        artist = artists.get(row["artist_mbid"])
        if artist is None:
            raise ValueError("recording provider artist missing from verified source cohort")
        matching = [r for r in artist["recordings"] if r["recording_mbid"] == row["recording_mbid"]]
        if len(matching) != 1:
            raise ValueError("recording destination has no unique exact credited recording")
        matching[0]["destinations"] = row["destinations"]
        matching[0]["destination_evidence"] = {
            "source_sha256": row["source_sha256"],
            "metadata_license": "CC0-1.0",
            "availability_checked": False,
            "audio_downloaded": False,
        }


def _verify_fma_projection(source: Path, projected: Path) -> dict[str, Any]:
    """Reconstruct every native CSV row with bounded memory and compare exact projection."""
    with tempfile.TemporaryDirectory(prefix="full-input-fma-replay-") as temporary:
        output = Path(temporary) / "projection"
        replayed = project_corpus(source, output)
        saved = json.loads((projected / "corpus-receipt.json").read_bytes())
        if replayed != saved:
            raise ValueError("full FMA corpus receipt differs from native reconstruction")
        for binding in saved["files"].values():
            if sha256_file(projected / binding["path"]) != sha256_file(output / binding["path"]):
                raise ValueError("full FMA projection differs from every native CSV row")
    return saved


def _rows(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream:
        return [json.loads(line) for line in io.TextIOWrapper(stream)]


def add_fma_context(artists: dict[str, dict[str, Any]], inputs: FullInputSources) -> dict[str, int]:
    """Bind exact FMA artist identities while keeping all genres at native track scope."""
    if not any((inputs.fma_source, inputs.fma_projection, inputs.fma_bridge, inputs.fma_static)):
        return {}
    if not all((inputs.fma_source, inputs.fma_projection, inputs.fma_bridge, inputs.fma_static)):
        raise ValueError(
            "FMA source, projection, bridge and full static catalog must be provided together"
        )
    assert inputs.fma_source is not None  # noqa: S101 - optional tuple checked above.
    assert inputs.fma_projection is not None  # noqa: S101 - validated optional tuple.
    assert inputs.fma_bridge is not None  # noqa: S101 - optional tuple checked above.
    assert inputs.fma_static is not None  # noqa: S101 - validated optional tuple.
    receipt = _verify_fma_projection(inputs.fma_source, inputs.fma_projection)
    bridge = verify_fma_exact_bridge(inputs.fma_bridge, inputs.fma_source)
    resolved = {row["fma_id"]: row for row in bridge["artist"]["resolved"]}
    native_artists = {
        row["artist_id"]: row
        for row in _rows(inputs.fma_projection / "artists.jsonl.zst")
        if row["artist_id"] in resolved
    }
    contexts: dict[int, dict[str, Any]] = {
        identity: {
            "fma_artist_id": identity,
            "track_ids": [],
            "genre_annotations": [],
            "source_artist": native_artists[identity],
            "license": "CC-BY-4.0",
            "attribution": receipt["attribution"],
            "scope": "native track annotations; not artist memberships",
            "bridge_evidence": resolved[identity],
            "url": f"fma/index.html#artist={identity}",
        }
        for identity in resolved
    }
    with (
        (inputs.fma_projection / "tracks.jsonl.zst").open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as stream,
    ):
        for line in io.TextIOWrapper(stream):
            row = json.loads(line)
            context = contexts.get(row["artist_id"])
            if context is not None:
                context["track_ids"].append(row["track_id"])
                context["genre_annotations"].append(
                    {"track_id": row["track_id"], "genre_ids": row["genre_ids"]}
                )
    for identity, context in contexts.items():
        for mbid in resolved[identity]["musicbrainz_mbids"]:
            artist = artists.setdefault(
                mbid,
                {
                    "artist_mbid": mbid,
                    "name": "",
                    "claims": [],
                    "direct_genres": [],
                    "recordings": [],
                    "links": [],
                    "native_sonic": [],
                },
            )
            artist.setdefault("fma_track_context", []).append(context)
    static = json.loads((inputs.fma_static / "static-receipt.json").read_bytes())
    if (
        static["corpus_receipt_sha256"]
        != sha256_file(inputs.fma_projection / "corpus-receipt.json")[0]
        or static["source_receipt_sha256"]
        != sha256_file(inputs.fma_source / "source-receipt.json")[0]
    ):
        raise ValueError("nested FMA catalog does not bind the replayed full corpus")
    if inputs.fma_listening_pack is not None:
        verify_fma_listening_pack(inputs.fma_listening_pack, inputs.fma_source)
    return {
        "fma_native_artists": bridge["artist"]["eligible"],
        "fma_exact_artist_bridges": len(resolved),
        "fma_native_tracks": bridge["recording"]["eligible"],
    }


def export_fma_context(inputs: FullInputSources, output: Path) -> None:
    """Clone only validated immutable FMA data and refresh its separately attributed UI."""
    if inputs.fma_static is not None:
        refresh_fma_static_display(source=inputs.fma_static, output=output / "fma")
    if inputs.fma_listening_pack is not None:
        if inputs.fma_source is None:
            raise ValueError("licensed listening requires its verified native metadata source")
        export_fma_listening(inputs.fma_listening_pack, inputs.fma_source, output / "fma-listening")


def verify_genre_context(inputs: FullInputSources, core: Path) -> dict[str, Any] | None:
    """Keep typed source hierarchy separate from musical distance and artist claims."""
    if inputs.genre_context_pack is None:
        return None
    if inputs.entity_pack is None:
        raise ValueError("native genre context requires its frozen exact-artist source pack")
    verify_genre_context_pack(inputs.genre_context_pack, inputs.entity_pack, core)
    return json.loads((inputs.genre_context_pack / "projection.json").read_bytes())
