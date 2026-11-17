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
