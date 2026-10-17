"""Independent equations and isolation contracts for the fixed feature map."""

import unittest
from dataclasses import fields

import numpy as np
from scipy import sparse

from opennoise.ml.fma_component_balanced import equal_component_weights
from opennoise.ml.fma_component_embedding import fit_embedding
from opennoise.ml.fma_fixed_nonlinear import fit_encoder, transform


class FixedNonlinearTests(unittest.TestCase):
    def fixture(self) -> tuple[np.ndarray, sparse.csr_matrix, np.ndarray, np.ndarray]:
        rng = np.random.default_rng(4)
        x = rng.normal(size=(80, 6))
        y = sparse.csr_matrix(rng.integers(0, 2, size=(80, 4)))
        return x, y, np.arange(80) < 60, np.arange(80) // 4  # noqa: PLR2004

    def test_heldout_features_targets_and_groups_cannot_affect_fit(self) -> None:
        x, y, fit, groups = self.fixture()
        for nonlinear in (False, True):
            model = fit_encoder(x, y, fit, groups, nonlinear=nonlinear)
            changed_x, changed_y, changed_groups = x.copy(), y.toarray(), groups.copy()
            changed_x[~fit], changed_y[~fit], changed_groups[~fit] = np.nan, 77, -999
            other = fit_encoder(
                changed_x, sparse.csr_matrix(changed_y), fit, changed_groups, nonlinear=nonlinear
            )
            for field in fields(model):
                np.testing.assert_array_equal(
                    getattr(model, field.name), getattr(other, field.name)
                )

    def test_dense_independent_centered_normal_equations(self) -> None:
        x, y, fit, groups = self.fixture()
        for nonlinear in (False, True):
            model = fit_encoder(x, y, fit, groups, nonlinear=nonlinear)
            z = (x[fit] - model.center) / model.scale
            phi = np.sqrt(2) * np.cos(z @ model.frequencies + model.phases) if nonlinear else z
            w = equal_component_weights(groups[fit])
            w /= w.sum()
            phi -= w @ phi
            yy = y[fit].toarray()[:, model.active_labels].astype(float)
            yy -= w @ yy
            expected = np.linalg.solve(
                phi.T @ (w[:, None] * phi) + np.eye(phi.shape[1]), phi.T @ (w[:, None] * yy)
            )
            np.testing.assert_allclose(model.coefficients, expected, atol=1e-14)

    def test_linear_matches_prior_solver_and_support_abstentions(self) -> None:
        x, y, fit, groups = self.fixture()
        model = fit_encoder(x, y, fit, groups, nonlinear=False)
        prior = fit_embedding(x, y, fit, groups)
        np.testing.assert_allclose(model.coefficients, prior.coefficients, atol=1e-14)
        rows = np.vstack([x[0], np.full(6, np.nan), model.center + 1000 * model.scale])
        vectors, ok = transform(model, rows)
        np.testing.assert_array_equal(ok, [True, False, False])
        np.testing.assert_array_equal(vectors[1:], 0)

    def test_zero_rank_and_constant_columns(self) -> None:
        x, y, fit, groups = self.fixture()
        x[:, 0] = 1
        y = sparse.csr_matrix(np.ones(y.shape))
        model = fit_encoder(x, y, fit, groups, nonlinear=True)
        self.assertFalse(model.active_columns[0])
        vector, ok = transform(model, x)
        self.assertEqual(vector.shape[0], len(x))
        self.assertFalse(ok.any())
