import unittest

from musix.ml.graph_metrics import weighted_undirected_modularity


class GraphMetricTests(unittest.TestCase):
    def test_modularity_includes_same_community_nonedge_expectations(self) -> None:
        weights = {("a", "b"): 1.0, ("c", "d"): 1.0}
        labels = {"a": "left", "b": "left", "c": "right", "d": "right"}

        # Each group contributes 1/2 - (2/4)^2 = 1/4.
        self.assertEqual(weighted_undirected_modularity(weights, labels), 0.5)

    def test_modularity_rejects_noncanonical_edges(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical endpoint order"):
            weighted_undirected_modularity({("b", "a"): 1.0}, {"a": "x", "b": "x"})


if __name__ == "__main__":
    unittest.main()
