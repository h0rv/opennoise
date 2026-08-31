"""Typed synchronous object storage contracts for streamed source artifacts."""

from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ObjectKey(_FrozenModel):
    """Represent one safe relative object key with POSIX separators."""

    value: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def safe_relative_key(self) -> "ObjectKey":
        """Reject absolute paths, empty parts, traversal, and platform separators."""
        if "\\" in self.value or "\0" in self.value:
            raise ValueError("object key contains an unsupported character")
        path = PurePosixPath(self.value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("object key must be a normalized relative path")
        if str(path) != self.value or self.value.endswith("/"):
            raise ValueError("object key must be a normalized relative path")
        return self

    @property
    def parts(self) -> tuple[str, ...]:
        """Return path parts only after validation has completed."""
        return PurePosixPath(self.value).parts


class ObjectWrite(_FrozenModel):
    """Report one immutable object publication."""

    key: ObjectKey
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    reused: bool


class ObjectRead(_FrozenModel):
    """Report one object copied to a local destination."""

    key: ObjectKey
    destination: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)


class ObjectStore(Protocol):
    """Expose the artifact operations shared by local and future remote stores."""

    def exists(self, key: ObjectKey) -> bool:
        """Return whether an immutable object exists."""
        ...

    def push(self, source: Path, key: ObjectKey) -> ObjectWrite:
        """Publish a local file under an immutable key."""
        ...

    def pull(self, key: ObjectKey, destination: Path) -> ObjectRead:
        """Copy an object to a local file through atomic publication."""
        ...
