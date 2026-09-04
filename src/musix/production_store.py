"""Read one sealed production map artifact without coupling it to SQLite layouts."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import quote

from pydantic import ValidationError

from musix.models import FrozenModel
from musix.models.production import ProductionMapArtifact
from musix.models.production_qa import ProductionMapOverviewCommunity  # noqa: TC001
from musix.overview import build_overview_communities

if TYPE_CHECKING:
    from pathlib import Path

_DETAIL_ROUTE_PREFIX: Final = "/genres/key/"


class ProductionMapStoreError(RuntimeError):
    """Report a configured production artifact that cannot be served safely."""


class ProductionMapApiResponse(FrozenModel):
    """Serve immutable graph data with local, stable public detail routes."""

    source: Literal["production-artifact"] = "production-artifact"
    fallback: Literal[False] = False
    graph: ProductionMapArtifact
    detail_hrefs: dict[str, str]
    overview_communities: tuple[ProductionMapOverviewCommunity, ...]


class ProductionMapStore:
    """Load and validate an optional static production artifact at most once."""

    def __init__(self, path: Path | None) -> None:
        """Bind one optional immutable artifact path for this process lifetime."""
        self._path = path
        self._lock = Lock()
        self._loaded = False
        self._artifact: ProductionMapArtifact | None = None
        self._error: str | None = None

    @property
    def configured(self) -> bool:
        """State whether this process was explicitly configured to serve production data."""
        return self._path is not None

    def response(self) -> ProductionMapApiResponse | None:
        """Return a safe graph payload, or legacy-fallback sentinel when unconfigured."""
        if not self.configured:
            return None
        with self._lock:
            self._load_once()
            if self._artifact is None:
                raise ProductionMapStoreError(self._error or "production map artifact unavailable")
            artifact = self._artifact
        return ProductionMapApiResponse(
            graph=artifact,
            detail_hrefs={
                node.genre_id: _DETAIL_ROUTE_PREFIX + quote(node.genre_id, safe="")
                for node in artifact.nodes
            },
            overview_communities=build_overview_communities(artifact),
        )

    def _load_once(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None:
            return
        try:
            payload = self._path.read_text(encoding="utf-8")
            self._artifact = ProductionMapArtifact.model_validate_json(payload)
        except (OSError, ValidationError, ValueError) as error:
            self._error = str(error)
