import numpy as np
from scipy import sparse

from opennoise.micro import jaccard, learned_words, split_name


def test_split_name_prefers_longest_place_and_known_style():
    words = {"new": 1, "new zealand": 2, "polish": 3}
    assert split_name("New Zealand Indie", words) == (2, "new zealand", "indie")
    assert split_name("polish black metal", words, {"black metal"}) == (3, "polish", "black metal")
    assert split_name("polish zzz", words, {"black metal"}) is None
    assert split_name("polish", words) is None


def test_learned_words_finds_unlisted_place_and_rejects_false_one():
    depth = sparse.csr_matrix((np.ones(10), (np.arange(10), [0] * 5 + [1] * 5)), shape=(100, 2))
    train = {
        "kiwi rock": np.array([0, 1, 2]),
        "kiwi pop": np.array([2, 3, 4]),
        "deep rock": np.array([5, 20, 21, 22]),
        "deep pop": np.array([23, 24, 25, 26]),
    }
    learned, rejected = learned_words(train, depth, {"deep": 1}, {"rock", "pop"})
    assert learned == {"kiwi": 0}
    assert rejected == {"deep"}


def test_jaccard():
    assert jaccard(np.array([1, 2, 3]), np.array([2, 3, 4])) == 0.5
