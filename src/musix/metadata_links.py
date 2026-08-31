"""Derive safe outbound metadata links from exact public identifiers."""

import re

from musix.models.modeling import MetadataKind

_MUSICBRAINZ_REFS = {
    "artist": re.compile(
        r"^musicbrainz:artist:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
    "release_group": re.compile(
        r"^musicbrainz:release-group:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
    "recording": re.compile(
        r"^musicbrainz:recording:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
    ),
}
_MUSICBRAINZ_PATHS: dict[MetadataKind, str] = {
    "artist": "artist",
    "release_group": "release-group",
    "recording": "recording",
}
_WIKIDATA_REFS = {
    kind: re.compile(rf"^wikidata:{kind.replace('_', '-')}:(Q[1-9][0-9]*)$")
    for kind in _MUSICBRAINZ_PATHS
}


def metadata_url(entity_kind: MetadataKind, source_entity_ref: str) -> str | None:
    """Return an ordinary metadata page only when kind and identifier agree exactly."""
    if match := _MUSICBRAINZ_REFS[entity_kind].fullmatch(source_entity_ref):
        return f"https://musicbrainz.org/{_MUSICBRAINZ_PATHS[entity_kind]}/{match.group(1)}"
    if match := _WIKIDATA_REFS[entity_kind].fullmatch(source_entity_ref):
        return f"https://www.wikidata.org/wiki/{match.group(1)}"
    return None
