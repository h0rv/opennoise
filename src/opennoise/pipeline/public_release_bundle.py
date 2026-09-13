"""Portable, cache-only custody bundles for the qualified public release.

The bundle deliberately contains the sealed *derived* cache and reproducibility
evidence.  It does not contain the raw 62-source vault and cannot be used to
claim a fresh source ingestion.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.pipeline.public_release_custody import (
    CustodyObject,
    EvidenceBinding,
    PublicReleaseCustodyReceipt,
)
from opennoise.pipeline.release_manifest import load_release_manifest
from opennoise.storage import ObjectKey, ObjectStore
from opennoise.types import Sha256  # noqa: TC001

_CHUNK_BYTES: Final = 1024 * 1024
_REVISION: Final = "public-release-custody-bundle-v1"
_RELEASE_FILE_NAMES: Final = (
    "release-manifest.json",
    "qualification-selection.json",
    *(f"music-genres-{ordinal:02d}.rq" for ordinal in range(8)),
)
_EVIDENCE_DESTINATIONS: Final[dict[str, tuple[Literal["evidence", "objective-gate"], str]]] = {
    "public-model": ("evidence", "public-model.json"),
    "production-map": ("evidence", "production-map-v1.json"),
    "production-map-acceptance": ("evidence", "production-map-v1.acceptance.json"),
    "production-map-seed-report": ("evidence", "production-map-v1.seed-report.json"),
    "production-map-browser": ("evidence", "production-map-v1.browser.json"),
    "production-map-report": ("evidence", "production-map-v1.report.json"),
    "release-receipt": ("evidence", "receipt.json"),
    "public-model-gate": ("objective-gate", "public-model-gate-v1.json"),
    "metadata-representatives": ("objective-gate", "metadata-representatives-v1.json"),
    "artist-membership-evaluation": ("objective-gate", "artist-membership-evaluation-v1.json"),
    "artist-membership-judgments": ("objective-gate", "artist-membership-judgments-v1.json"),
    "musicbrainz-core-metadata-hydration": (
        "evidence",
        "musicbrainz-release-tracks.json",
    ),
    "musicbrainz-core-metadata-hydration-report": (
        "evidence",
        "musicbrainz-release-tracks.report.json",
    ),
    "representative-catalog-candidates": (
        "evidence",
        "representative-candidates-v1.json",
    ),
    "representative-catalog-candidates-report": (
        "evidence",
        "representative-candidates-v1.report.json",
    ),
    "open-construction-graph": ("evidence", "open-construction-graph-v1.json"),
    "open-construction-graph-gate": (
        "evidence",
        "open-construction-graph-v1.gate.json",
    ),
    "open-construction-graph-receipt": (
        "evidence",
        "open-construction-graph-v1.receipt.json",
    ),
}

_BASE_EVIDENCE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "public-model",
        "production-map",
        "production-map-acceptance",
        "production-map-seed-report",
        "production-map-browser",
        "production-map-report",
        "release-receipt",
    }
)
_OPTIONAL_EVIDENCE_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset(
        {"musicbrainz-core-metadata-hydration", "musicbrainz-core-metadata-hydration-report"}
    ),
    frozenset({"representative-catalog-candidates", "representative-catalog-candidates-report"}),
    frozenset(
        {
            "open-construction-graph",
            "open-construction-graph-gate",
            "open-construction-graph-receipt",
        }
    ),
    frozenset({"phase4-api-source-qa", "phase4-integration-report"}),
)


class PublicReleaseBundleError(ValueError):
    """Report a bundle that cannot reproduce the sealed cache-only release."""


class BundleObject(FrozenModel):
    """One immutable object stored under a relative object-store key."""

    key: ObjectKey
    sha256: Sha256
    byte_size: int = Field(ge=0)


class PublicReleaseBundleEntry(FrozenModel):
    """One object and its safe, explicit restore destination."""

    kind: Literal["cache", "release-config", "evidence", "objective-gate", "custody-receipt"]
    object: BundleObject
    restore_path: ObjectKey


class PublicReleaseCustodyBundleReceipt(FrozenModel):
    """Deterministic manifest for a portable sealed-derived-cache bundle."""

    revision: Literal["public-release-custody-bundle-v1"] = _REVISION
    release_id: str = Field(min_length=1, max_length=300)
    reproduction_scope: Literal["sealed-derived-cache-and-evidence"] = (
        "sealed-derived-cache-and-evidence"
    )
    raw_source_reingestion: Literal["not-included"] = "not-included"
    custody_receipt_sha256: Sha256
    entries: tuple[PublicReleaseBundleEntry, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def complete_and_unambiguous(self) -> PublicReleaseCustodyBundleReceipt:  # noqa: C901
        """Require a closed, restore-safe set of derived-release members."""
        keys = tuple(item.object.key.value for item in self.entries)
        paths = tuple(item.restore_path.value for item in self.entries)
        if len(set(keys)) != len(keys) or len(set(paths)) != len(paths):
            raise ValueError("bundle object keys and restore paths must be unique")
        kinds = tuple(item.kind for item in self.entries)
        if kinds.count("cache") != 1 or kinds.count("custody-receipt") != 1:
            raise ValueError("bundle must contain exactly one cache and custody receipt")
        if kinds.count("release-config") != len(_RELEASE_FILE_NAMES):
            raise ValueError("bundle must contain the complete release configuration")
        required_evidence = _BASE_EVIDENCE_NAMES
        present_evidence = {
            item.restore_path.value
            for item in self.entries
            if item.kind in {"evidence", "objective-gate"}
        }
        expected_evidence = {path for _, path in _EVIDENCE_DESTINATIONS.values()}
        # Objective gates are either both present or both absent in a custody receipt.
        required_base = {_EVIDENCE_DESTINATIONS[name][1] for name in _BASE_EVIDENCE_NAMES}
        if not required_base <= present_evidence:
            raise ValueError("bundle is missing required release evidence")
        if present_evidence - expected_evidence or not present_evidence <= expected_evidence:
            raise ValueError("bundle contains an unexpected evidence destination")
        if ("public-model-gate-v1.json" in present_evidence) != (
            "metadata-representatives-v1.json" in present_evidence
        ):
            raise ValueError("bundle objective gates must be present as a pair")
        if ("artist-membership-evaluation-v1.json" in present_evidence) != (
            "artist-membership-judgments-v1.json" in present_evidence
        ):
            raise ValueError("bundle artist membership evidence must be present as a pair")
        present_names = {
            name for name, (_, path) in _EVIDENCE_DESTINATIONS.items() if path in present_evidence
        }
        for group in _OPTIONAL_EVIDENCE_GROUPS:
            if bool(group & present_names) and not group <= present_names:
                raise ValueError("bundle optional integrated evidence is incomplete")
        if not required_evidence:  # Keep the static table visibly total for the checker.
            raise ValueError("bundle evidence table is unexpectedly empty")
        return self


class PublicReleaseBundleDestinations(FrozenModel):
    """Explicit destinations for restoring one bundle into a checkout."""

    cache_database: Path
    release_directory: Path
    evidence_directory: Path
    objective_gates_directory: Path
    custody_receipt: Path


class RestoredPublicReleaseBundle(FrozenModel):
    """Verified outcome of restoring every bundle member."""

    receipt: PublicReleaseCustodyBundleReceipt
    restored: tuple[PublicReleaseBundleEntry, ...]


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _read_custody_receipt(path: Path) -> PublicReleaseCustodyReceipt:
    try:
        return PublicReleaseCustodyReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PublicReleaseBundleError("custody receipt is missing or malformed") from error


def _read_bundle_receipt(store: ObjectStore, key: ObjectKey) -> PublicReleaseCustodyBundleReceipt:
    with tempfile.TemporaryDirectory(prefix="opennoise-public-release-bundle-") as directory:
        path = Path(directory) / "receipt.json"
        try:
            stored = store.pull(key, path)
            observed = _hash_file(path)
            if observed != (stored.sha256, stored.byte_size):
                raise PublicReleaseBundleError(
                    "object store returned an inconsistent bundle receipt"
                )
            return PublicReleaseCustodyBundleReceipt.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            if isinstance(error, PublicReleaseBundleError):
                raise
            raise PublicReleaseBundleError("bundle receipt is missing or malformed") from error


def _bundle_prefix(custody_receipt_sha256: str) -> str:
    return f"bundles/public-release/v1/{custody_receipt_sha256}"


def bundle_receipt_key(custody_receipt_sha256: Sha256) -> ObjectKey:
    """Return the deterministic key of the bundle receipt for a custody receipt hash."""
    return ObjectKey(value=f"{_bundle_prefix(custody_receipt_sha256)}/receipt.json")


def _bundle_object_key(custody_receipt_sha256: str, sha256: str) -> ObjectKey:
    return ObjectKey(value=f"{_bundle_prefix(custody_receipt_sha256)}/objects/sha256/{sha256}")


def _verify_object(store: ObjectStore, object_: BundleObject) -> None:
    with tempfile.TemporaryDirectory(prefix="opennoise-public-release-bundle-") as directory:
        path = Path(directory) / "object"
        try:
            copied = store.pull(object_.key, path)
        except OSError as error:
            raise PublicReleaseBundleError(
                f"bundle object is missing: {object_.key.value}"
            ) from error
        observed = _hash_file(path)
        if observed != (object_.sha256, object_.byte_size) or observed != (
            copied.sha256,
            copied.byte_size,
        ):
            raise PublicReleaseBundleError(
                f"bundle object hash or size differs: {object_.key.value}"
            )


def _copy_from_store(
    source_store: ObjectStore,
    source: CustodyObject,
    bundle_store: ObjectStore,
    custody_receipt_sha256: str,
) -> BundleObject:
    with tempfile.TemporaryDirectory(prefix="opennoise-public-release-bundle-") as directory:
        temporary = Path(directory) / "object"
        try:
            pulled = source_store.pull(source.key, temporary)
        except OSError as error:
            raise PublicReleaseBundleError(
                f"custody object is missing: {source.key.value}"
            ) from error
        observed = _hash_file(temporary)
        if observed != (source.sha256, source.byte_size) or observed != (
            pulled.sha256,
            pulled.byte_size,
        ):
            raise PublicReleaseBundleError(
                f"custody object hash or size differs: {source.key.value}"
            )
        key = _bundle_object_key(custody_receipt_sha256, source.sha256)
        written = bundle_store.push(temporary, key)
        if (written.sha256, written.byte_size) != observed:
            raise PublicReleaseBundleError("bundle object store changed copied bytes")
        return BundleObject(key=key, sha256=written.sha256, byte_size=written.byte_size)


def _push_file(path: Path, bundle_store: ObjectStore, custody_receipt_sha256: str) -> BundleObject:
    if not path.is_file():
        raise PublicReleaseBundleError(f"required bundle input is missing: {path}")
    sha256, byte_size = _hash_file(path)
    key = _bundle_object_key(custody_receipt_sha256, sha256)
    written = bundle_store.push(path, key)
    if (written.sha256, written.byte_size) != (sha256, byte_size):
        raise PublicReleaseBundleError(f"bundle object store changed verified bytes for {path}")
    return BundleObject(key=key, sha256=sha256, byte_size=byte_size)


def _custody_evidence(receipt: PublicReleaseCustodyReceipt) -> dict[str, EvidenceBinding]:
    evidence = {item.name: item for item in receipt.evidence}
    if len(evidence) != len(receipt.evidence) or set(evidence) - set(_EVIDENCE_DESTINATIONS):
        raise PublicReleaseBundleError(
            "custody receipt evidence names are ambiguous or unsupported"
        )
    required = _BASE_EVIDENCE_NAMES
    if not required <= set(evidence):
        raise PublicReleaseBundleError("custody receipt is missing release evidence")
    gates = {"public-model-gate", "metadata-representatives"}
    if (gates <= set(evidence)) != (receipt.objective_gate_state == "present"):
        raise PublicReleaseBundleError("custody receipt objective-gate state is inconsistent")
    artist_evidence = {"artist-membership-evaluation", "artist-membership-judgments"}
    names = set(evidence)
    if bool(artist_evidence & names) and not artist_evidence <= names:
        raise PublicReleaseBundleError("custody receipt artist membership evidence is incomplete")
    for group in _OPTIONAL_EVIDENCE_GROUPS:
        if bool(group & names) and not group <= names:
            raise PublicReleaseBundleError(
                "custody receipt optional integrated evidence is incomplete"
            )
    return evidence


def export_public_release_bundle(
    *,
    custody_receipt_path: Path,
    release_directory: Path,
    custody_store: ObjectStore,
    bundle_store: ObjectStore,
) -> tuple[PublicReleaseCustodyBundleReceipt, ObjectKey]:
    """Copy the sealed cache and evidence into a deterministic portable object set."""
    custody_receipt = _read_custody_receipt(custody_receipt_path)
    custody_sha256, _ = _hash_file(custody_receipt_path)
    try:
        manifest = load_release_manifest(release_directory)
    except ValueError as error:
        raise PublicReleaseBundleError("release configuration is missing or malformed") from error
    if manifest["release_id"] != custody_receipt.release_id:
        raise PublicReleaseBundleError(
            "release configuration and custody receipt identify different releases"
        )
    evidence = _custody_evidence(custody_receipt)
    entries: list[PublicReleaseBundleEntry] = [
        PublicReleaseBundleEntry(
            kind="cache",
            object=_copy_from_store(
                custody_store, custody_receipt.cache, bundle_store, custody_sha256
            ),
            restore_path=ObjectKey(value="cache/phase3-public-qualified.sqlite"),
        ),
        PublicReleaseBundleEntry(
            kind="custody-receipt",
            object=_push_file(custody_receipt_path, bundle_store, custody_sha256),
            restore_path=ObjectKey(value="receipts/public-release-custody-receipt.json"),
        ),
    ]
    entries.extend(
        PublicReleaseBundleEntry(
            kind="release-config",
            object=_push_file(release_directory / filename, bundle_store, custody_sha256),
            restore_path=ObjectKey(value=f"release-config/{filename}"),
        )
        for filename in _RELEASE_FILE_NAMES
    )
    entries.extend(
        PublicReleaseBundleEntry(
            kind=_EVIDENCE_DESTINATIONS[name][0],
            object=_copy_from_store(custody_store, evidence[name], bundle_store, custody_sha256),
            restore_path=ObjectKey(value=_EVIDENCE_DESTINATIONS[name][1]),
        )
        for name in sorted(evidence)
    )
    receipt = PublicReleaseCustodyBundleReceipt(
        release_id=custody_receipt.release_id,
        custody_receipt_sha256=custody_sha256,
        entries=tuple(entries),
    )
    key = bundle_receipt_key(receipt.custody_receipt_sha256)
    _publish_receipt(bundle_store, key, receipt)
    verify_public_release_bundle(bundle_store, key)
    return receipt, key


def _publish_receipt(
    store: ObjectStore, key: ObjectKey, receipt: PublicReleaseCustodyBundleReceipt
) -> None:
    with tempfile.TemporaryDirectory(prefix="opennoise-public-release-bundle-") as directory:
        path = Path(directory) / "receipt.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write((receipt.model_dump_json(indent=2) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            store.push(path, key)
        except OSError as error:
            raise PublicReleaseBundleError(
                "bundle receipt could not be published atomically"
            ) from error


def verify_public_release_bundle(
    store: ObjectStore, receipt_key: ObjectKey
) -> PublicReleaseCustodyBundleReceipt:
    """Fail closed if a bundle manifest, object, hash, or safe path is incomplete."""
    receipt = _read_bundle_receipt(store, receipt_key)
    for entry in receipt.entries:
        _verify_object(store, entry.object)
    custody_entry = next(item for item in receipt.entries if item.kind == "custody-receipt")
    if custody_entry.object.sha256 != receipt.custody_receipt_sha256:
        raise PublicReleaseBundleError("bundle custody receipt hash differs from its manifest")
    _verify_bundle_bindings(store, receipt, custody_entry)
    return receipt


def _verify_bundle_bindings(
    store: ObjectStore,
    receipt: PublicReleaseCustodyBundleReceipt,
    custody_entry: PublicReleaseBundleEntry,
) -> None:
    """Parse nested boundary documents and match every sealed copied object."""
    with tempfile.TemporaryDirectory(prefix="opennoise-public-release-bundle-") as directory:
        root = Path(directory)
        custody_path = root / "custody.json"
        store.pull(custody_entry.object.key, custody_path)
        custody = _read_custody_receipt(custody_path)
        if custody.release_id != receipt.release_id:
            raise PublicReleaseBundleError("bundle and custody receipt identify different releases")
        entries = {entry.restore_path.value: entry for entry in receipt.entries}
        cache = entries.get("cache/phase3-public-qualified.sqlite")
        if (
            cache is None
            or cache.object.sha256 != custody.cache.sha256
            or (cache.object.byte_size != custody.cache.byte_size)
        ):
            raise PublicReleaseBundleError("bundle cache differs from the sealed custody cache")
        for name, bound in _custody_evidence(custody).items():
            kind, filename = _EVIDENCE_DESTINATIONS[name]
            entry = entries.get(filename)
            if (
                entry is None
                or entry.kind != kind
                or entry.object.sha256 != bound.sha256
                or (entry.object.byte_size != bound.byte_size)
            ):
                raise PublicReleaseBundleError(
                    f"bundle evidence differs from custody receipt: {name}"
                )
        config_root = root / "release-config"
        for entry in receipt.entries:
            if entry.kind == "release-config":
                store.pull(entry.object.key, config_root.joinpath(*entry.restore_path.parts[1:]))
        try:
            manifest = load_release_manifest(config_root)
        except ValueError as error:
            raise PublicReleaseBundleError("bundle release configuration is malformed") from error
        if manifest["release_id"] != receipt.release_id:
            raise PublicReleaseBundleError(
                "bundle release configuration identifies another release"
            )


def _restore_destination(
    entry: PublicReleaseBundleEntry, destinations: PublicReleaseBundleDestinations
) -> Path:
    relative_parts = entry.restore_path.parts
    match entry.kind:
        case "cache":
            return destinations.cache_database
        case "custody-receipt":
            return destinations.custody_receipt
        case "release-config":
            root = destinations.release_directory
            relative_parts = relative_parts[1:]
        case "evidence":
            root = destinations.evidence_directory
        case "objective-gate":
            root = destinations.objective_gates_directory
    target = root.joinpath(*relative_parts)
    if not target.resolve(strict=False).is_relative_to(root.resolve()):
        raise PublicReleaseBundleError("bundle restore path escapes its explicit destination")
    return target


def restore_public_release_bundle(
    *,
    store: ObjectStore,
    receipt_key: ObjectKey,
    destinations: PublicReleaseBundleDestinations,
) -> RestoredPublicReleaseBundle:
    """Verify then atomically restore every sealed object to caller-chosen paths."""
    receipt = verify_public_release_bundle(store, receipt_key)
    for entry in receipt.entries:
        destination = _restore_destination(entry, destinations)
        try:
            pulled = store.pull(entry.object.key, destination)
        except OSError as error:
            raise PublicReleaseBundleError(
                f"bundle object could not be restored: {entry.object.key.value}"
            ) from error
        observed = _hash_file(destination)
        if observed != (entry.object.sha256, entry.object.byte_size) or observed != (
            pulled.sha256,
            pulled.byte_size,
        ):
            raise PublicReleaseBundleError(f"restored bytes differ: {entry.object.key.value}")
    load_release_manifest(destinations.release_directory)
    return RestoredPublicReleaseBundle(receipt=receipt, restored=receipt.entries)
