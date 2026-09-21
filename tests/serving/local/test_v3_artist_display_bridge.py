# ruff: noqa: SLF001

import hashlib
import sqlite3
import unittest
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opennoise.deployment.static_discovery import (
    StaticDiscoveryArtistPayload,
    StaticDiscoveryCoveragePayload,
    StaticDiscoveryEvidencePayload,
    StaticDiscoveryMembershipPayload,
    StaticDiscoveryPayload,
    StaticDiscoverySourcePayload,
)
from opennoise.serving.local import v3_artist_display_bridge as bridge
from opennoise.serving.local.v3_artist_display_bridge import (
    V3ArtistDisplayBridgeError,
    V3ArtistDisplayBridgeInputs,
    build_local_v3_artist_display_bridge_audit,
)
from tests._pinned_v1_discovery import pinned_v1_discovery_path

_V3_ROOT = Path("/tmp/phase3-historical-v3-20260921")  # noqa: S108 - pinned local input.
_STATIC_DISCOVERY = pinned_v1_discovery_path()
_PINNED_INPUTS = (
    _V3_ROOT / "receipt.json",
    _V3_ROOT / "model.json",
    _V3_ROOT / "serving.sqlite",
    _STATIC_DISCOVERY,
)


class V3ArtistDisplayBridgeTests(unittest.TestCase):
    def test_hermetic_exact_identity_matches_and_abstains_without_retained_inputs(self) -> None:
        inputs = V3ArtistDisplayBridgeInputs(
            v3_receipt=Path("receipt.json"),
            v3_model=Path("model.json"),
            v3_serving_database=Path("serving.sqlite"),
            static_discovery=Path("static-discovery.json"),
        )
        direct_profiles = Counter({_MBID_A: 2, _MBID_B: 1})
        static_artists = {_MBID_A: ("static-artist-a", "Authorized Artist")}
        with (
            patch.object(bridge, "_load_receipt", return_value=object()),
            patch.object(bridge, "_load_model"),
            patch.object(bridge, "_direct_profile_memberships", return_value=direct_profiles),
            patch.object(bridge, "_load_static_artists", return_value=static_artists),
            patch.object(bridge, "_file_sha256", return_value="0" * 64),
        ):
            audit = build_local_v3_artist_display_bridge_audit(inputs)

        self.assertEqual(
            audit.coverage.model_dump(),
            {
                "v3_direct_profile_artist_count": 2,
                "v3_direct_profile_membership_count": 3,
                "static_display_artist_count": 1,
                "static_artist_with_exact_musicbrainz_id_count": 1,
                "exact_identity_match_count": 1,
                "display_authorized_match_count": 1,
                "v3_abstained_artist_count": 1,
                "static_unmatched_artist_count": 0,
            },
        )
        self.assertEqual(audit.links[0].artist_musicbrainz_id, _MBID_A)
        self.assertEqual(audit.links[0].display_name, "Authorized Artist")

    def test_hermetic_static_artist_boundary_rejects_ambiguous_or_incomplete_records(self) -> None:
        cases = {
            "duplicate MusicBrainz ID": (_artist(_MBID_A, "one"), _artist(_MBID_A, "two")),
            "duplicate static ID": (_artist(_MBID_A, "one"), _artist(_MBID_B, "one")),
            "missing MusicBrainz URL": (_artist(None, "one"),),
            "missing display name": (_artist(_MBID_A, "one", name=" "),),
            "missing membership": (_artist(_MBID_A, "one", memberships=()),),
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "static-discovery.json"
            with patch.object(bridge, "_file_sha256", return_value=bridge._STATIC_DISCOVERY_SHA256):
                for label, artists in cases.items():
                    with self.subTest(label=label):
                        path.write_text(_static_payload(artists).model_dump_json())
                        with self.assertRaisesRegex(V3ArtistDisplayBridgeError, "identity|display"):
                            bridge._load_static_artists(path)

    def test_hermetic_direct_profile_boundary_rejects_bad_refs_and_wrong_schema(self) -> None:
        receipt = _ReceiptStub(bridge._V3_SERVING_DATABASE_SHA256, 7)
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "serving.sqlite"
            _write_direct_profiles(database, [_MBID_A], schema_version=7)
            with patch.object(
                bridge, "_file_sha256", return_value=bridge._V3_SERVING_DATABASE_SHA256
            ):
                self.assertEqual(
                    bridge._direct_profile_memberships(database, receipt), Counter({_MBID_A: 1})
                )
            _write_direct_profiles(database, ["not-an-artist-ref"], schema_version=7)
            with (
                patch.object(
                    bridge, "_file_sha256", return_value=bridge._V3_SERVING_DATABASE_SHA256
                ),
                self.assertRaisesRegex(V3ArtistDisplayBridgeError, "non-MusicBrainz"),
            ):
                bridge._direct_profile_memberships(database, receipt)
            _write_direct_profiles(database, [_MBID_A], schema_version=8)
            with (
                patch.object(
                    bridge, "_file_sha256", return_value=bridge._V3_SERVING_DATABASE_SHA256
                ),
                self.assertRaisesRegex(V3ArtistDisplayBridgeError, "integrity or schema"),
            ):
                bridge._direct_profile_memberships(database, receipt)

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "pinned local v3 or static-discovery input is unavailable",
    )
    def test_pinned_inputs_replay_an_exact_display_authorized_identity_bridge(self) -> None:
        inputs = _pinned_inputs()
        before = {path: _file_sha256(path) for path in _input_paths(inputs)}

        audit = build_local_v3_artist_display_bridge_audit(inputs)

        self.assertEqual(before, {path: _file_sha256(path) for path in _input_paths(inputs)})
        self.assertEqual(
            audit.coverage.model_dump(),
            {
                "v3_direct_profile_artist_count": 1205,
                "v3_direct_profile_membership_count": 4434,
                "static_display_artist_count": 1008,
                "static_artist_with_exact_musicbrainz_id_count": 1008,
                "exact_identity_match_count": 1008,
                "display_authorized_match_count": 1008,
                "v3_abstained_artist_count": 197,
                "static_unmatched_artist_count": 0,
            },
        )
        self.assertEqual(len(audit.links), 1008)
        self.assertFalse(audit.export_allowed)
        self.assertFalse(audit.static_output_written)
        self.assertFalse(audit.map_output_written)
        self.assertFalse(audit.historical_inputs_used)

    @unittest.skipUnless(
        _STATIC_DISCOVERY.is_file(), "pinned static discovery input is unavailable"
    )
    def test_rejects_an_invalid_receipt_before_opening_later_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            inputs = V3ArtistDisplayBridgeInputs(
                v3_receipt=Path(temporary) / "receipt.json",
                v3_model=Path(temporary) / "model.json",
                v3_serving_database=Path(temporary) / "serving.sqlite",
                static_discovery=_STATIC_DISCOVERY,
            )
            with self.assertRaisesRegex(V3ArtistDisplayBridgeError, "input cannot be read"):
                build_local_v3_artist_display_bridge_audit(inputs)

    @unittest.skipUnless(
        all(path.is_file() for path in _PINNED_INPUTS),
        "pinned local v3 or static-discovery input is unavailable",
    )
    def test_rejects_a_byte_modified_display_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            altered = Path(temporary) / "static-discovery.json"
            altered.write_bytes(_STATIC_DISCOVERY.read_bytes() + b"\n")
            inputs = _pinned_inputs(static_discovery=altered)
            with self.assertRaisesRegex(V3ArtistDisplayBridgeError, "static discovery file hash"):
                build_local_v3_artist_display_bridge_audit(inputs)

    def test_has_no_output_path_or_artifact_writer(self) -> None:
        self.assertEqual(
            set(V3ArtistDisplayBridgeInputs.model_fields),
            {
                "v3_receipt",
                "v3_model",
                "v3_serving_database",
                "static_discovery",
            },
        )


def _pinned_inputs(static_discovery: Path = _STATIC_DISCOVERY) -> V3ArtistDisplayBridgeInputs:
    return V3ArtistDisplayBridgeInputs(
        v3_receipt=_V3_ROOT / "receipt.json",
        v3_model=_V3_ROOT / "model.json",
        v3_serving_database=_V3_ROOT / "serving.sqlite",
        static_discovery=static_discovery,
    )


def _input_paths(inputs: V3ArtistDisplayBridgeInputs) -> tuple[Path, ...]:
    return (inputs.v3_receipt, inputs.v3_model, inputs.v3_serving_database, inputs.static_discovery)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


_MBID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_MBID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@dataclass(frozen=True)
class _ReceiptStub:
    serving_database_sha256: str
    serving_database_schema_version: int


def _artist(
    musicbrainz_id: str | None,
    artist_id: str,
    *,
    name: str = "Authorized Artist",
    memberships: tuple[StaticDiscoveryMembershipPayload, ...] | None = None,
) -> StaticDiscoveryArtistPayload:
    return StaticDiscoveryArtistPayload(
        artist_id=artist_id,
        name=name,
        musicbrainz_url=(
            f"https://musicbrainz.org/artist/{musicbrainz_id}" if musicbrainz_id else None
        ),
        memberships=_membership() if memberships is None else memberships,
        shared_genre_artists=(),
    )


def _membership() -> tuple[StaticDiscoveryMembershipPayload, ...]:
    return (
        StaticDiscoveryMembershipPayload(
            node_id="item1",
            catalog_genre_id=1,
            catalog_genre_name="Genre",
            binding="exact_casefolded_label",
            evidence=(
                StaticDiscoveryEvidencePayload(
                    evidence_id=1,
                    source_key="source",
                    source_record_id="record",
                    method_key="method",
                    method_version="v1",
                    provenance_id=1,
                ),
            ),
        ),
    )


def _static_payload(
    artists: tuple[StaticDiscoveryArtistPayload, ...],
) -> StaticDiscoveryPayload:
    return StaticDiscoveryPayload(
        revision="static-direct-discovery-v1",
        availability="ready",
        source=StaticDiscoverySourcePayload(
            database_sha256=bridge._STATIC_PUBLIC_DATABASE_SHA256,
            database_byte_count=1,
            observation_kind="direct_source_claim",
            sources=(),
        ),
        coverage=StaticDiscoveryCoveragePayload(
            placed_map_node_count=1,
            exact_label_bound_catalog_genre_count=1,
            genres_with_direct_artists=1,
            artists_with_direct_map_genres=len(artists),
            direct_catalog_observation_count=len(artists),
            bound_direct_observation_count=len(artists),
            artist_relation_method="shared_direct_catalog_genre",
            unserved_colisten_reason="active_display_policy_denies_colisten",
        ),
        artists=artists,
    )


def _write_direct_profiles(database: Path, artist_ids: list[str], *, schema_version: int) -> None:
    if database.exists():
        database.unlink()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f"PRAGMA user_version = {schema_version}")
        connection.execute(
            "CREATE TABLE public_genre_profile_memberships "
            "(source_artist_ref TEXT, profile_kind TEXT)"
        )
        connection.executemany(
            "INSERT INTO public_genre_profile_memberships VALUES (?, 'direct')",
            [(f"musicbrainz:artist:{artist_id}",) for artist_id in artist_ids],
        )
        connection.commit()
