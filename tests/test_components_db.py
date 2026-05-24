"""Tests for the v1.6 unified component database.

Covers:
* Registry shape (every entry is a Component; aliases resolve correctly).
* Back-compat: every species that was in v1.5.3 SHOMATE / ANTOINE / MW /
  H_REF_298 is still present with identical numeric values.
* Tier-2 species carry the critical-property triple (Tc, Pc, ω) needed for
  the upcoming PR/SRK property packages.
* Critical-property sanity: Tc > Tb > Tm for every species that has all
  three; Pc > 0; -1 < ω < 1; MW > 0.
"""

from __future__ import annotations

import math

import pytest

from pse_ecosystem.models.properties import components as cdb
from pse_ecosystem.models.properties.components import (
    Component,
    REGISTRY,
    get,
    has_antoine,
    has_eos_params,
    has_shomate,
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry shape
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistryShape:
    def test_registry_is_non_empty(self):
        assert len(REGISTRY) > 0

    def test_all_entries_are_components(self):
        for key, c in REGISTRY.items():
            assert isinstance(c, Component), f"REGISTRY[{key!r}] is not a Component"

    def test_canonical_id_in_registry(self):
        for c in set(REGISTRY.values()):
            assert REGISTRY[c.id] is c

    def test_aliases_resolve_to_same_component(self):
        for c in set(REGISTRY.values()):
            for alias in c.aliases:
                assert REGISTRY[alias] is c, (
                    f"Alias {alias!r} on {c.id!r} resolves to a different Component"
                )

    def test_methane_aliases(self):
        """'CH4' and 'methane' must resolve to the same Component."""
        assert get("CH4") is get("methane")

    def test_water_aliases(self):
        assert get("H2O") is get("water")

    def test_h2_aliases(self):
        assert get("H2") is get("hydrogen")

    def test_get_raises_keyerror_for_unknown(self):
        with pytest.raises(KeyError):
            get("definitely_not_a_real_species")


# ─────────────────────────────────────────────────────────────────────────────
# Back-compat: v1.5.3 SHOMATE / ANTOINE / MW / H_REF_298 numerics
# ─────────────────────────────────────────────────────────────────────────────


_V153_SHOMATE_KEYS = {"H2", "O2", "N2", "CO", "CO2", "CH4", "H2O"}
_V153_ANTOINE_KEYS = {
    "benzene", "toluene", "n-hexane", "n-heptane",
    "methanol", "ethanol", "water",
    "H2", "CO2", "methane",
}
_V153_MW = {
    "H2": 2.016, "O2": 31.999, "N2": 28.014,
    "CO": 28.010, "CO2": 44.010, "CH4": 16.043, "H2O": 18.015,
}
_V153_H_REF_298 = {
    "H2": 0.0, "O2": 0.0, "N2": 0.0,
    "CO": -110527.0, "CO2": -393510.0,
    "CH4": -74873.0, "H2O": -241826.0,
}
_V153_SHOMATE_SAMPLE = {
    # Spot-check the Shomate A coefficient — full row match implied by the
    # property tests in test_properties.py.
    "H2": 33.066178, "O2": 31.32234, "N2": 28.98641,
    "CO": 25.567959, "CO2": 24.997557, "CH4": -0.703029, "H2O": 30.092000,
}
_V153_ANTOINE_SAMPLE = {
    "benzene": (6.90565, 1211.033, 220.790),
    "water":   (8.07131, 1730.630, 233.426),
    "methane": (6.69561, 405.420, 267.780),
}


class TestBackCompatSHOMATE:
    def test_legacy_keys_present(self):
        shomate = cdb._build_shomate_dict()
        assert set(shomate.keys()) >= _V153_SHOMATE_KEYS

    def test_shomate_does_not_emit_aliases(self):
        """Legacy callers iterate ``SHOMATE.keys()`` — aliases must NOT appear."""
        shomate = cdb._build_shomate_dict()
        assert "methane" not in shomate  # only "CH4"
        assert "water" not in shomate    # only "H2O"
        assert "hydrogen" not in shomate

    def test_shomate_A_coefficient_matches(self):
        shomate = cdb._build_shomate_dict()
        for sp, expected_A in _V153_SHOMATE_SAMPLE.items():
            assert shomate[sp]["A"] == expected_A

    def test_shomate_T_range_matches(self):
        shomate = cdb._build_shomate_dict()
        assert shomate["H2"]["T_min"] == 298 and shomate["H2"]["T_max"] == 1000
        assert shomate["CO"]["T_min"] == 298 and shomate["CO"]["T_max"] == 1300
        assert shomate["H2O"]["T_max"] == 1700


class TestBackCompatANTOINE:
    def test_legacy_keys_present(self):
        antoine = cdb._build_antoine_dict()
        assert set(antoine.keys()) >= _V153_ANTOINE_KEYS

    def test_both_methane_aliases_present(self):
        """v1.5.3 used 'methane' in ANTOINE but 'CH4' in SHOMATE — both
        must continue to resolve in the rebuilt ANTOINE dict."""
        antoine = cdb._build_antoine_dict()
        assert "methane" in antoine
        assert "CH4" in antoine
        assert antoine["methane"]["A"] == antoine["CH4"]["A"]

    def test_antoine_coefficients_match(self):
        antoine = cdb._build_antoine_dict()
        for sp, (A, B, C) in _V153_ANTOINE_SAMPLE.items():
            assert antoine[sp]["A"] == A
            assert antoine[sp]["B"] == B
            assert antoine[sp]["C"] == C


class TestBackCompatMW:
    def test_legacy_mw_values(self):
        mw = cdb._build_mw_dict()
        for sp, expected in _V153_MW.items():
            assert mw[sp] == expected

    def test_mw_dict_does_not_include_eos_only_species(self):
        """The legacy MW dict carried molecular weights only for Shomate-
        bearing species. New Tier-2 species (e.g. ethane) have MW on the
        Component but must NOT leak into the legacy dict, since callers
        use ``if sp in MW`` as a proxy for 'is this an ideal-gas species'.
        """
        mw = cdb._build_mw_dict()
        assert "ethane" not in mw
        assert "propane" not in mw
        assert "ammonia" not in mw


class TestBackCompatHREF298:
    def test_legacy_hf_values(self):
        href = cdb._build_hf_298_dict()
        for sp, expected in _V153_H_REF_298.items():
            assert abs(href[sp] - expected) < 1e-9, (
                f"H_REF_298[{sp!r}] = {href[sp]} but v1.5.3 had {expected}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Tier-2 species — cubic-EOS readiness
# ─────────────────────────────────────────────────────────────────────────────


_TIER2_NEW_SPECIES = [
    "ethane", "propane", "n-butane", "i-butane", "n-pentane",
    "ethylene", "propylene", "cyclohexane", "p-xylene",
    "n-propanol", "isopropanol", "n-butanol", "ethylene_glycol",
    "acetone", "acetic_acid", "ammonia", "MEA",
    "H2S", "SO2", "Ar",
]


class TestTier2Coverage:
    @pytest.mark.parametrize("species", _TIER2_NEW_SPECIES)
    def test_has_eos_params(self, species):
        assert has_eos_params(species), (
            f"{species} missing Tc/Pc/ω — cannot be used in PR/SRK"
        )

    @pytest.mark.parametrize("species", _TIER2_NEW_SPECIES)
    def test_has_mw(self, species):
        c = get(species)
        assert c.MW > 0, f"{species} has zero MW"

    def test_count_at_least_25_distinct_species(self):
        distinct = {c.id for c in REGISTRY.values()}
        assert len(distinct) >= 25, (
            f"Expected ≥25 distinct species, registry has {len(distinct)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Physical-property sanity
# ─────────────────────────────────────────────────────────────────────────────


class TestPropertySanity:
    def test_critical_temperature_above_boiling_point(self):
        for c in set(REGISTRY.values()):
            if c.Tc_K is not None and c.Tb_K is not None:
                assert c.Tc_K > c.Tb_K, f"{c.id}: Tc ({c.Tc_K}) <= Tb ({c.Tb_K})"

    # Species that sublime at 1 atm — Tb_K stores the sublimation point and
    # Tm_K stores the triple-point temperature, so Tb_K < Tm_K is the
    # physically correct ordering.
    _SUBLIMATING = {"CO2"}

    def test_boiling_point_above_melting_point(self):
        for c in set(REGISTRY.values()):
            if c.id in self._SUBLIMATING:
                continue
            if c.Tb_K is not None and c.Tm_K is not None:
                assert c.Tb_K > c.Tm_K, f"{c.id}: Tb ({c.Tb_K}) <= Tm ({c.Tm_K})"

    def test_critical_pressure_positive(self):
        for c in set(REGISTRY.values()):
            if c.Pc_Pa is not None:
                assert c.Pc_Pa > 0, f"{c.id}: Pc must be positive"

    def test_acentric_factor_in_physical_range(self):
        # ω is typically in (-0.3, 1.0); H2's value of -0.220 is the most
        # negative legitimate entry. Anything outside (-0.5, 1.0) is suspect.
        for c in set(REGISTRY.values()):
            if c.omega is not None:
                assert -0.5 < c.omega < 1.0, (
                    f"{c.id}: ω = {c.omega} outside physical range"
                )

    def test_no_zero_molecular_weight(self):
        for c in set(REGISTRY.values()):
            assert c.MW > 0, f"{c.id}: MW must be positive"


# ─────────────────────────────────────────────────────────────────────────────
# Helper predicates
# ─────────────────────────────────────────────────────────────────────────────


class TestHelperPredicates:
    def test_has_shomate_true_for_known(self):
        assert has_shomate("H2O")
        assert has_shomate("CO2")

    def test_has_shomate_false_for_eos_only(self):
        assert not has_shomate("ethane")
        assert not has_shomate("propane")

    def test_has_antoine_true_for_known(self):
        assert has_antoine("benzene")
        assert has_antoine("ethanol")
        assert has_antoine("ethane")  # added in Tier 2

    def test_has_eos_params_false_for_underspecified(self):
        # Argon has Tc/Pc/ω but no antoine — EOS yes, Antoine no
        assert has_eos_params("Ar")
        assert not has_antoine("Ar")
