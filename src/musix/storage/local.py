"""Streaming local filesystem implementation of the object store contract."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from musix.policy import require_metadata_file
from musix.storage.base import ObjectKey, ObjectMetadata, ObjectRead, ObjectWrite

COPY_CHUNK_BYTES = 1024 * 1024


class ObjectStoreError(RuntimeError):
    """Report an invalid local object store operation."""


class ObjectConflictError(ObjectStoreError):
    """Report an immutable key that already has different content."""


def _copy_and_hash(source: BinaryIO, destination: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    while chunk := source.read(COPY_CHUNK_BYTES):
        digest.update(chunk)
        destination.write(chunk)
        byte_size += len(chunk)
    destination.flush()
    os.fsync(destination.fileno())
    return digest.hexdigest(), byte_size


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _temporary_path(parent: Path, name: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=parent)
    os.close(descriptor)
    return Path(raw_path)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LocalObjectStore:
    """Store immutable objects below one local root without loading them into memory."""

    def __init__(self, root: Path) -> None:
        """Create the store root and retain its resolved boundary."""
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()

    def _object_path(self, key: ObjectKey) -> Path:
        path = self._root.joinpath(*key.parts)
        current = self._root
        for part in key.parts:
            current /= part
            if current.is_symlink():
                raise ObjectStoreError("object key contains a symbolic link")
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise ObjectStoreError("object key resolves outside the store root")
        return path

    def exists(self, key: ObjectKey) -> bool:
        """Return whether a regular file exists for the key."""
        return self._object_path(key).is_file()

    def inspect(self, key: ObjectKey) -> ObjectMetadata:
        """Hash a stored object in place without creating a temporary copy."""
        source = self._object_path(key)
        if not source.is_file():
            raise FileNotFoundError(f"object key {key.value!r} does not exist")
        sha256, byte_size = _hash_file(source)
        return ObjectMetadata(key=key, sha256=sha256, byte_size=byte_size)

    def _push_sync(self, source: Path, key: ObjectKey) -> ObjectWrite:
        if not source.is_file():
            raise ObjectStoreError("push source must be a regular file")
        require_metadata_file(source)
        destination = self._object_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = _temporary_path(destination.parent, destination.name)
        try:
            with source.open("rb") as source_stream, temporary.open("wb") as target_stream:
                source_sha256, source_size = _copy_and_hash(source_stream, target_stream)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                stored_sha256, stored_size = _hash_file(destination)
                if (stored_sha256, stored_size) != (source_sha256, source_size):
                    raise ObjectConflictError(
                        f"object key {key.value!r} already contains different content"
                    ) from None
                reused = True
            else:
                reused = False
                _fsync_directory(destination.parent)
            return ObjectWrite(
                key=key,
                sha256=source_sha256,
                byte_size=source_size,
                reused=reused,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def push(self, source: Path, key: ObjectKey) -> ObjectWrite:
        """Stream and atomically publish one immutable local file."""
        return self._push_sync(source, key)

    def _pull_sync(self, key: ObjectKey, destination: Path) -> ObjectRead:
        source = self._object_path(key)
        if not source.is_file():
            raise FileNotFoundError(f"object key {key.value!r} does not exist")
        require_metadata_file(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = _temporary_path(destination.parent, destination.name)
        try:
            with source.open("rb") as source_stream, temporary.open("wb") as target_stream:
                sha256, byte_size = _copy_and_hash(source_stream, target_stream)
            temporary.replace(destination)
            _fsync_directory(destination.parent)
            return ObjectRead(
                key=key,
                destination=destination,
                sha256=sha256,
                byte_size=byte_size,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def pull(self, key: ObjectKey, destination: Path) -> ObjectRead:
        """Stream an object to a temporary file and atomically publish it."""
        return self._pull_sync(key, destination)
