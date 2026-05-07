"""BaseUnit sanity checks: finite-difference Jacobian fallback vs analytical."""

from __future__ import annotations

import numpy as np
import pytest

from pse_ecosystem.core.contracts import PrimalGuess
from pse_ecosystem.models.base_unit import BaseUnit
from pse_ecosystem.models.electrolysis.pem_toy import PEMToy
from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy


@pytest.fixture
def gasifier() -> GasifierToy:
    return GasifierToy(unit_id="gasifier")


def test_pem_is_linear_and_exact(monkeypatch):
    pem = PEMToy(unit_id="pem")
    guess = PrimalGuess(values={pem.v_electricity: 5_000.0, pem.v_h2: 0.0})

    lin = pem.linearize(guess)

    assert lin.is_exact is True
    assert pem.is_linear is True
    assert lin.J.shape == (1, 2)
    # Residual at guess: h2 - eta * electricity
    expected_f0 = 0.0 - pem.params.eta_kg_per_kWh * 5_000.0
    np.testing.assert_allclose(lin.f0, [expected_f0])


def test_fd_fallback_matches_analytical_gasifier(gasifier: GasifierToy):
    """The default FD linearize on BaseUnit should produce the same Jacobian
    as the gasifier's hand-derived analytical override."""
    guess = PrimalGuess(
        values={
            gasifier.v_feed: 12_000.0,
            gasifier.v_h2: 1_000.0,
            gasifier.v_steam: 6_000.0,
        }
    )

    lin_analytical = gasifier.linearize(guess)
    lin_fd = BaseUnit.linearize(gasifier, guess)

    np.testing.assert_allclose(lin_analytical.f0, lin_fd.f0, atol=1e-9)
    np.testing.assert_allclose(lin_analytical.J, lin_fd.J, atol=1e-5)


def test_predicted_residual_is_self_consistent(gasifier: GasifierToy):
    """f0 + J · (x - x0) at x = x0 must equal f0."""
    guess = PrimalGuess(
        values={
            gasifier.v_feed: 8_000.0,
            gasifier.v_h2: 700.0,
            gasifier.v_steam: 4_000.0,
        }
    )
    lin = gasifier.linearize(guess)
    predicted = lin.predicted_residual(guess.values)
    np.testing.assert_allclose(predicted, lin.f0, atol=1e-12)


def test_bounds_aggregation(gasifier: GasifierToy):
    bounds = gasifier.bounds()
    assert bounds[gasifier.v_feed] == (0.0, gasifier.params.feed_max_kg_per_h)
    assert bounds[gasifier.v_h2][1] == gasifier.params.a * gasifier.params.feed_max_kg_per_h
