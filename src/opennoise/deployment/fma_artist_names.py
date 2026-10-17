"""Display-only names supplied unanimously by tracks with a missing artist record."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

TRACK_NAME_SOURCE = "unanimous_track_artist_name"


def track_artist_names(tracks: list[dict[str, Any]], known_artist_ids: set[int]) -> dict[int, str]:
    """Keep exact nonempty strings only when every track for one native ID agrees.

    Missing or conflicting names abstain. Null artist IDs cannot identify an
    artist. Equal names under distinct native IDs never merge identities. This
    helper does not repair the source artist table or change missing-ID status.
    """
    names: dict[int, set[str]] = defaultdict(set)
    incomplete: set[int] = set()
    for track in tracks:
        artist_id = track["artist_id"]
        if type(artist_id) is not int or artist_id <= 0 or artist_id in known_artist_ids:
            continue
        name = track.get("artist_name")
        if not isinstance(name, str) or not name.strip():
            incomplete.add(artist_id)
        else:
            names[artist_id].add(name)
    return {
        artist_id: next(iter(values))
        for artist_id, values in sorted(names.items())
        if len(values) == 1 and artist_id not in incomplete
    }
