from opennoise.names import canonical, clean


def genre(id_, name, count, parent=None):
    return {"id": id_, "name": name, "aliases": [], "parent_id": parent, "member_count": count}


def test_canonical_expands_acronyms_and_spellings():
    assert canonical("Polish IDM") == "polish intelligent dance music"
    assert canonical("uk r&b") == "uk rhythm and blues"
    assert canonical("drum n bass") == "drum and bass"
    assert canonical("christian hip-hop") == "christian hip hop"
    assert canonical("forro") == "forró"


def test_clean_merges_duplicates_and_keeps_aliases():
    genres = [
        genre("a", "idm", 5),
        genre("b", "intelligent dance music", 9),
        genre("c", "pop music", 2),
        genre("d", "pop", 7),
        genre("e", "idm · Aphex Twin", 1, "a"),
    ]
    report = clean(genres, {"a": ["Autechre"], "c": ["Madonna"]})
    by = {g["id"]: g for g in genres}
    assert report == {"renamed": 3, "merged": 2}
    assert by["a"]["parent_id"] == "b" and by["a"]["name"] == "intelligent dance music · Autechre"
    assert by["e"]["parent_id"] == "b" and by["e"]["name"] == "intelligent dance music · Aphex Twin"
    assert by["c"]["name"] == "pop · Madonna"
    assert "idm" in by["b"]["aliases"] and "pop music" in by["d"]["aliases"]
