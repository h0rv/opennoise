import pytest

from opennoise.identities import assign


def record(key, members, name="Same name"):
    return {"key": key, "members": sorted(members), "name": name, "scope": "level"}


def test_registry_stability(tmp_path):
    path = tmp_path / "registry.json"
    records = [record("one", "abcde"), record("two", "fghij")]
    first = assign(path, records)
    snapshot = path.read_bytes()
    assert assign(path, list(reversed(records))) == first
    assert path.read_bytes() == snapshot
    assert first["one"]["id"] != first["two"]["id"]
    renamed = assign(path, [record("one", "abcde", "New name"), records[1]])
    assert renamed["one"]["id"] == first["one"]["id"]
    assert renamed["one"]["aliases"] == ["Same name"]
    moved = assign(path, [record("new signature", "abcd", "New name"), records[1]])
    assert moved["new signature"]["id"] == first["one"]["id"]


def test_registry_split_merge_and_retirement(tmp_path):
    path = tmp_path / "registry.json"
    original = assign(path, [record("whole", "abcde")])["whole"]["id"]
    split = assign(path, [record("left", "ab", "Left"), record("right", "cde", "Right")])
    assert original not in {r["id"] for r in split.values()}
    merged = assign(path, [record("whole", "abcde", "Merged")])["whole"]
    assert merged["id"] == split["right"]["id"]
    assert merged["aliases"] == ["Left", "Right"]


def test_registry_empty_and_invalid(tmp_path):
    path = tmp_path / "registry.json"
    assert assign(path, []) == {}
    with pytest.raises(ValueError, match="duplicate genre keys"):
        assign(path, [record("duplicate", "a"), record("duplicate", "b")])
