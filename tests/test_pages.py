import gzip
import json

import pytest

from opennoise.pages import pack, pack_file


def test_pack(tmp_path):
    source = tmp_path / "release"
    (source / "artists").mkdir(parents=True)
    (source / "genres").mkdir()
    similar = [{"id": str(i), "score": 0.123456} for i in range(50)]
    (source / "artists/a.json").write_text(json.dumps({"similar": similar, "name": "é"}))
    (source / "genres/g.json").write_text(json.dumps({"similar": similar}))
    (source / "manifest.json").write_text('{"value":1.234567,"empty":[],"null":null}')
    target = tmp_path / "catalog"
    pack(source, target)
    assert len(list(target.rglob("*.json"))) == 3
    artist = json.loads(gzip.decompress((target / "artists/a.json").read_bytes()))
    assert artist == {"similar": [{"id": str(i), "score": 0.1235} for i in range(20)], "name": "é"}
    genre = json.loads(gzip.decompress((target / "genres/g.json").read_bytes()))
    assert len(genre["similar"]) == 50
    assert gzip.decompress((target / "manifest.json").read_bytes()) == (
        b'{"value":1.2346,"empty":[],"null":null}'
    )


def test_pack_empty_and_invalid(tmp_path):
    source = tmp_path / "release"
    source.mkdir()
    pack(source, tmp_path / "empty")
    with pytest.raises(ValueError, match="outside"):
        pack(source, source / "catalog")
    with pytest.raises(NotADirectoryError):
        pack(tmp_path / "missing", tmp_path / "catalog")
    invalid = source / "bad.json"
    invalid.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        pack_file((invalid, tmp_path / "bad.json"))


def test_pack_ranks_genre_ties_by_in_genre_support(tmp_path):
    (tmp_path / "artists").mkdir()
    (tmp_path / "genres").mkdir()
    members = [
        {"artist": {"id": id_, "listeners": listeners}, "score": score}
        for id_, listeners, score in [("anchor", 1, 0.8), ("a", 100, 0.5), ("b", 10, 0.5)]
    ]
    for id_, neighbor in [("a", "outside"), ("b", "anchor")]:
        (tmp_path / "artists" / f"{id_}.json").write_text(
            json.dumps({"similar": [{"artist": {"id": neighbor}, "score": 1.0}]})
        )
    source, target = tmp_path / "genres/g.json", tmp_path / "packed.json"
    source.write_text(json.dumps({"members": members}))
    pack_file((source, target))
    packed = json.loads(gzip.decompress(target.read_bytes()))["members"]
    assert packed == [members[0], members[2], members[1]]
