"""Independent whole-track connectivity guard for historical FMA artist splits."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from opennoise.ml.fma_acoustic_baseline import NativeTrack


def _root(parents: list[int], index: int) -> int:
    while True:
        parent = int(parents[index])
        if parent == index:
            return index
        parents[index] = parents[parent]
        index = parent


def _join_duplicates(
    positions: Mapping[int, int],
    groups: Sequence[Sequence[int]],
    union: Callable[[int, int], None],
) -> None:
    for group in groups:
        members = (positions[identity] for identity in group if identity in positions)
        owner = next(members, None)
        if owner is not None:
            for index in members:
                union(owner, index)


def audit_native_components(
    tracks: Sequence[NativeTrack],
    duplicate_groups: Sequence[Sequence[int]],
    components: Mapping[int, int],
) -> None:
    """Reject v2 components separated by supplied album/duplicate bridge tracks.

    Missing artists remain unknown, but their tracks still transmit known album
    and duplicate edges. This check never changes historical component identifiers
    or grants isolated status where source identities are absent.
    """
    positions = {row.track_id: index for index, row in enumerate(tracks)}
    if len(positions) != len(tracks):
        raise ValueError("native component audit requires distinct track IDs")
    artists = {row.artist_id for row in tracks if row.artist_id is not None}
    if set(components) != artists:
        raise ValueError("native component audit must cover every supplied artist exactly")
    parents = list(range(len(tracks)))

    def union(left: int, right: int) -> None:
        a, b = _root(parents, left), _root(parents, right)
        parents[max(a, b)] = min(a, b)

    artist_owners: dict[int, int] = {}
    album_owners: dict[int, int] = {}
    for index, row in enumerate(tracks):
        if row.artist_id is not None:
            union(index, artist_owners.setdefault(row.artist_id, index))
        if row.album_id is not None:
            union(index, album_owners.setdefault(row.album_id, index))
    _join_duplicates(positions, duplicate_groups, union)

    emitted: dict[int, int] = {}
    for index, row in enumerate(tracks):
        if row.artist_id is not None:
            component = components[row.artist_id]
            if emitted.setdefault(_root(parents, index), component) != component:
                raise ValueError(
                    "historical FMA v2 components split a connected artist/album/duplicate "
                    "track graph; a fresh split revision and new evaluation are required"
                )
