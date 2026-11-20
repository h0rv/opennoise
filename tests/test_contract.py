import json
import shutil
from pathlib import Path

import pytest
from jsonschema_rs import meta

from opennoise.contract import SCHEMA, validate_release

FIXTURE = Path(__file__).parent / "fixtures/catalog"
ARTIST = "artists/00000000-0000-4000-8000-000000000001.json"


@pytest.fixture
def release(tmp_path):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def change(root, filename, mutate):
    path = root / filename
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))


def test_fixture():
    meta.validate(SCHEMA)
    assert validate_release(FIXTURE)["data_kind"] == "synthetic"


@pytest.mark.parametrize(
    ("filename", "mutate", "error"),
    [
        ("manifest.json", lambda d: d.update(schema_version=2), "manifest.json"),
        ("manifest.json", lambda d: d.update(genres="../genres.json"), "manifest.json"),
        ("manifest.json", lambda d: d.update(similarity=None), "similarity is unavailable"),
        ("manifest.json", lambda d: d["layouts"].update(axes=None), "unavailable layout"),
        ("genres.json", lambda d: d.append(d[0]), "Duplicate"),
        ("genres.json", lambda d: d[0].update(parent_id="absent"), "hierarchy"),
        ("genres.json", lambda d: d[0].update(parent_id="techno"), "hierarchy"),
        ("search.json", lambda d: d.pop(0), "every genre"),
        ("search.json", lambda d: d[0].update(name="Renamed"), "search entry"),
        (ARTIST, lambda d: d["artist"].update(id="../../secret"), ARTIST),
        (ARTIST, lambda d: d["artist"]["positions"]["axes"].update(x=-1), ARTIST),
        (ARTIST, lambda d: d["artist"]["positions"]["axes"].update(x=float("nan")), "Non-finite"),
        (ARTIST, lambda d: d["artist"].update(color="#bad-color"), ARTIST),
        (ARTIST, lambda d: d["genres"][0].update(id="absent"), "references"),
        (ARTIST, lambda d: d["genres"].reverse(), "score-descending"),
        (ARTIST, lambda d: d["genres"][0].update(score=0.99), "membership directions"),
        (ARTIST, lambda d: d["similar"].append(d["similar"][0]), "references"),
        (ARTIST, lambda d: d["similar"][0].update(artist=d["artist"]), "references"),
        (ARTIST, lambda d: d["similar"][0]["artist"].update(name="Wrong"), "artist"),
        (ARTIST, lambda d: d.update(preview={"provider": "deezer", "url": "https://x"}), ARTIST),
        (
            ARTIST,
            lambda d: d.update(links=[{"label": "Bad", "url": "javascript:alert(1)"}]),
            ARTIST,
        ),
        (ARTIST, lambda d: d.update(links=[{"label": "Bad", "url": "https://bad uri"}]), ARTIST),
        ("genres/house.json", lambda d: d["members"].clear(), "member count"),
        ("genres/house.json", lambda d: d["genre"].update(name="Wrong"), "genre detail"),
    ],
)
def test_rejects_broken_release(release, filename, mutate, error):
    change(release, filename, mutate)
    with pytest.raises(ValueError, match=error):
        validate_release(release)


def test_requires_detail_for_every_search_result(release):
    (release / ARTIST).unlink()
    with pytest.raises(ValueError, match=ARTIST):
        validate_release(release)


def test_uncomputed_release(release):
    manifest = json.loads((release / "manifest.json").read_text())
    manifest.update(layouts={"axes": None, "islands": None})
    manifest.update(membership=None, similarity=None, genre_similarity=None)
    (release / "manifest.json").write_text(json.dumps(manifest))
    artist = json.loads((release / ARTIST).read_text())
    artist["artist"].update(positions={"axes": None, "islands": None}, listeners=0)
    artist.update(genres=None, similar=None, signals=[], links=[], preview=None)
    (release / ARTIST).write_text(json.dumps(artist))
    (release / "genres.json").write_text("[]")
    (release / "search.json").write_text(
        json.dumps(
            [
                {
                    "kind": "artist",
                    "id": artist["artist"]["id"],
                    "name": artist["artist"]["name"],
                    "aliases": [],
                }
            ]
        )
    )
    assert validate_release(release)["layouts"] == {"axes": None, "islands": None}
