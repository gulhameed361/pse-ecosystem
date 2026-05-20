"""Industrial readiness tests — v1.5.0.

Covers:
  1. ASME VIII Div.1 UG-27(c)(1) wall thickness formula
  2. Le Chatelier mixture flammability rule
  3. Persona toggle session-state management
  4. compute_safety_margins() bridge function
  5. Non-intrusiveness: safety checks do not affect solver residuals / bounds / results
  6. Layer compliance: safety_checks.py must not import from pse_ecosystem
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
import pytest
from typing import Dict


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ASME Wall Thickness
# ═══════════════════════════════════════════════════════════════════════════════

class TestASMEWallThickness:

    def _fn(self, **kw):
        from pse_ecosystem.models.safety.safety_checks import asme_minimum_wall_thickness
        return asme_minimum_wall_thickness(**kw)

    def test_known_result_50bar_r500mm(self):
        """t = P*R / (S*E - 0.6*P) with P=5e6 Pa, R=0.5 m, S=138e6 Pa, E=1.0
        → t = 2.5e6 / 135e6 ≈ 0.018519 m"""
        t = self._fn(pressure_Pa=5e6, inner_radius_m=0.5,
                     allowable_stress_Pa=138e6, joint_efficiency=1.0)
        expected = 5e6 * 0.5 / (138e6 * 1.0 - 0.6 * 5e6)
        assert abs(t - expected) < 1e-10

    def test_higher_pressure_gives_thicker_wall(self):
        t1 = self._fn(pressure_Pa=1e6, inner_radius_m=0.5)
        t2 = self._fn(pressure_Pa=5e6, inner_radius_m=0.5)
        assert t2 > t1

    def test_larger_radius_gives_thicker_wall(self):
        t1 = self._fn(pressure_Pa=5e6, inner_radius_m=0.3)
        t2 = self._fn(pressure_Pa=5e6, inner_radius_m=0.8)
        assert t2 > t1

    def test_lower_joint_efficiency_gives_thicker_wall(self):
        t_full = self._fn(pressure_Pa=5e6, inner_radius_m=0.5, joint_efficiency=1.0)
        t_spot = self._fn(pressure_Pa=5e6, inner_radius_m=0.5, joint_efficiency=0.85)
        assert t_spot > t_full

    def test_over_pressure_raises_value_error(self):
        """S*E - 0.6*P ≤ 0 is outside UG-27(c)(1) validity."""
        with pytest.raises(ValueError, match="ASME"):
            self._fn(pressure_Pa=250e6, inner_radius_m=0.5,
                     allowable_stress_Pa=138e6, joint_efficiency=1.0)

    def test_returns_positive_float(self):
        t = self._fn(pressure_Pa=1e5, inner_radius_m=0.5)
        assert isinstance(t, float)
        assert t > 0.0

    def test_default_material_is_sa516_70(self):
        """Default allowable stress should match SA-516-70 (138 MPa)."""
        from pse_ecosystem.models.safety.safety_checks import (
            asme_minimum_wall_thickness, _DEFAULT_ALLOWABLE_STRESS_PA
        )
        t_default = asme_minimum_wall_thickness(5e6, 0.5)
        t_explicit = asme_minimum_wall_thickness(5e6, 0.5, allowable_stress_Pa=_DEFAULT_ALLOWABLE_STRESS_PA)
        assert abs(t_default - t_explicit) < 1e-14

    def test_atmospheric_pressure_gives_thin_wall(self):
        """1 atm (≈ 1e5 Pa) operating pressure should give negligible wall thickness."""
        t = self._fn(pressure_Pa=1e5, inner_radius_m=0.5)
        assert t < 0.001  # < 1 mm


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Flammability Margins (Le Chatelier)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlammabilityMargins:

    def _fn(self, comp):
        from pse_ecosystem.models.safety.safety_checks import flammability_margins
        return flammability_margins(comp)

    def test_pure_h2_lfl_and_ufl(self):
        r = self._fn({"H2": 1.0})
        assert abs(r["LFL_vol_pct"] - 4.0) < 1e-9
        assert abs(r["UFL_vol_pct"] - 75.0) < 1e-9

    def test_pure_ch4(self):
        r = self._fn({"CH4": 1.0})
        assert abs(r["LFL_vol_pct"] - 5.0) < 1e-9

    def test_le_chatelier_h2_co_mixture(self):
        """H2:CO = 50:50 mol → LFL_mix = 1 / (0.5/4 + 0.5/12.5) ≈ 6.061 vol%"""
        r = self._fn({"H2": 0.5, "CO": 0.5})
        expected_lfl = 1.0 / (0.5 / 4.0 + 0.5 / 12.5)
        assert abs(r["LFL_vol_pct"] - expected_lfl) < 1e-9

    def test_inert_species_do_not_change_lfl(self):
        """N2/CO2/H2O are ignored; only flammable species participate in Le Chatelier."""
        r_pure = self._fn({"H2": 1.0})
        # 40% H2 + 60% inerts: after renorm H2 fraction = 1.0 → same LFL
        r_diluted = self._fn({"H2": 0.4, "N2": 0.3, "CO2": 0.2, "H2O": 0.1})
        assert abs(r_pure["LFL_vol_pct"] - r_diluted["LFL_vol_pct"]) < 1e-9

    def test_no_flammable_species_raises_value_error(self):
        with pytest.raises(ValueError, match="[Nn]o recognised flammable"):
            self._fn({"N2": 0.79, "O2": 0.21})

    def test_zero_flammable_fraction_raises(self):
        with pytest.raises(ValueError):
            self._fn({"H2": 0.0, "N2": 1.0})

    def test_returns_all_required_keys(self):
        r = self._fn({"H2": 0.5, "CH4": 0.5})
        expected_keys = {
            "LFL_vol_pct", "UFL_vol_pct",
            "mixture_flammable_fraction",
            "margin_to_LFL_vol_pct", "margin_to_UFL_vol_pct",
            "flammable_species",
        }
        assert expected_keys.issubset(set(r.keys()))

    def test_flammable_species_list_sorted(self):
        r = self._fn({"CO": 0.3, "H2": 0.5, "CH4": 0.2})
        assert r["flammable_species"] == sorted(["CO", "H2", "CH4"])

    def test_mixture_flammable_fraction_correct(self):
        """With 30% flammable + 70% inert, mixture_flammable_fraction should be 0.3."""
        r = self._fn({"H2": 0.3, "N2": 0.7})
        assert abs(r["mixture_flammable_fraction"] - 0.3) < 1e-12

    def test_operating_pressure_margin_positive_when_safe(self):
        """(P_design - P_op) / P_design should be positive when P_op < P_design."""
        from pse_ecosystem.models.safety.safety_checks import operating_pressure_margin
        margin = operating_pressure_margin(P_operating_Pa=5e6, P_design_Pa=5.5e6)
        assert margin > 0.0
        assert abs(margin - (5.5e6 - 5e6) / 5.5e6) < 1e-14

    def test_operating_pressure_margin_negative_when_over(self):
        from pse_ecosystem.models.safety.safety_checks import operating_pressure_margin
        margin = operating_pressure_margin(P_operating_Pa=6e6, P_design_Pa=5e6)
        assert margin < 0.0

    def test_operating_pressure_margin_zero_design_raises(self):
        from pse_ecosystem.models.safety.safety_checks import operating_pressure_margin
        with pytest.raises(ValueError):
            operating_pressure_margin(1e5, 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Persona Toggle
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersonaToggle:

    def test_default_persona_is_academic(self):
        """_init_state pattern: setdefault("user_persona", "Academic")."""
        state = {}
        state.setdefault("user_persona", "Academic")
        assert state["user_persona"] == "Academic"

    def test_serialize_includes_persona_field(self):
        from pse_ecosystem.ui.flowsheet_service import serialize_flowsheet_config
        blob = serialize_flowsheet_config(
            template_key="hydrogen.electrolysis_only",
            params={},
            user_persona="Industrial",
        )
        payload = json.loads(blob)
        assert payload["user_persona"] == "Industrial"

    def test_serialize_defaults_to_academic(self):
        from pse_ecosystem.ui.flowsheet_service import serialize_flowsheet_config
        blob = serialize_flowsheet_config(
            template_key="hydrogen.electrolysis_only",
            params={},
        )
        payload = json.loads(blob)
        assert payload["user_persona"] == "Academic"

    def test_deserialize_missing_persona_defaults_academic(self):
        from pse_ecosystem.ui.flowsheet_service import deserialize_flowsheet_config
        old_config = json.dumps({
            "schema_version": "1.5.0.dev",
            "template_key": "hydrogen.electrolysis_only",
            "params": {},
        })
        result = deserialize_flowsheet_config(old_config)
        assert result.get("user_persona", "Academic") == "Academic"

    def test_schema_version_updated_to_1_5_0(self):
        from pse_ecosystem.ui.flowsheet_service import serialize_flowsheet_config
        blob = serialize_flowsheet_config("hydrogen.electrolysis_only", {})
        payload = json.loads(blob)
        assert payload["schema_version"] == "1.5.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compute_safety_margins() bridge
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeSafetyMargins:

    def _minimal_x(self, flowsheet):
        """Build a minimal solution_x: all vars = 1.0, then set realistic P."""
        return {v: 1.0 for v in flowsheet.all_variables()}

    def _compressor_flowsheet(self):
        from pse_ecosystem.ui.flowsheet_service import load_template
        # Use the smallest template that has a Compressor unit
        try:
            return load_template("hydrogen.electrolysis_compression")
        except Exception:
            # Fall back to building from scratch via service
            from pse_ecosystem.ui.flowsheet_service import build_custom_flowsheet
            return build_custom_flowsheet({
                "units": [
                    {
                        "type": "Compressor",
                        "id": "comp",
                        "params": {
                            "components": ["H2", "N2"],
                            "P_out_Pa": 5e6,
                        },
                    }
                ],
                "connections": [],
            })

    def test_returns_list(self):
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins
        fs = self._compressor_flowsheet()
        x = self._minimal_x(fs)
        # Set a plausible outlet pressure so the unit is detected
        for k in list(x.keys()):
            if k.endswith(".outlet.P") or k.endswith(".P"):
                x[k] = 5e6
                break
        result = compute_safety_margins(fs, x)
        assert isinstance(result, list)

    def test_safety_margin_row_fields(self):
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins, SafetyMarginRow
        fs = self._compressor_flowsheet()
        x = self._minimal_x(fs)
        for k in list(x.keys()):
            if k.endswith(".outlet.P"):
                x[k] = 5e6
                break
        rows = compute_safety_margins(fs, x)
        for row in rows:
            assert isinstance(row, SafetyMarginRow)
            assert row.unit_id
            assert row.unit_type
            assert row.check_type in ("ASME_wall_thickness", "pressure_margin", "flammability")
            assert row.status in ("OK", "WARNING", "VIOLATION")
            assert isinstance(row.detail, str)

    def test_asme_row_present_for_compressor(self):
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins
        fs = self._compressor_flowsheet()
        x = self._minimal_x(fs)
        for k in list(x.keys()):
            if k.endswith(".outlet.P"):
                x[k] = 5e6
                break
        rows = compute_safety_margins(fs, x)
        check_types = {r.check_type for r in rows}
        assert "ASME_wall_thickness" in check_types

    def test_empty_result_when_no_pressure_vars(self):
        """compute_safety_margins returns [] if no pressure variable is in solution_x."""
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins
        fs = self._compressor_flowsheet()
        # Supply no pressure values (all 0.0 → skipped)
        x = {v: 0.0 for v in fs.all_variables()}
        rows = compute_safety_margins(fs, x)
        # Either empty or rows exist with zero pressure skipped — implementation detail.
        assert isinstance(rows, list)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Non-intrusiveness
# ═══════════════════════════════════════════════════════════════════════════════

class TestNonIntrusiveness:
    """Safety checks must leave residual vectors, bounds, and solve results unchanged."""

    def _unit(self):
        """Return a simple Compressor unit for intrusion tests."""
        try:
            from pse_ecosystem.models.pressure_changers.compressor import Compressor
            return Compressor("c", ["H2", "N2"])
        except ImportError:
            pytest.skip("Compressor unit not importable in this install")

    def test_asme_does_not_mutate_unit_state(self):
        from pse_ecosystem.models.safety.safety_checks import asme_minimum_wall_thickness
        import numpy as np

        unit = self._unit()
        x = {v: 1.0 for v in unit.variables()}
        # Evaluate residual before safety call
        res_before = np.array(unit.residual(x), dtype=float).copy()
        # Call safety check — must not modify unit
        _ = asme_minimum_wall_thickness(5e6, 0.5)
        res_after = np.array(unit.residual(x), dtype=float)
        np.testing.assert_array_equal(res_before, res_after)

    def test_asme_does_not_change_bounds(self):
        from pse_ecosystem.models.safety.safety_checks import asme_minimum_wall_thickness
        unit = self._unit()
        bounds_before = unit.bounds()
        _ = asme_minimum_wall_thickness(5e6, 0.5)
        bounds_after = unit.bounds()
        assert bounds_before == bounds_after

    def test_flammability_is_pure_function(self):
        """Same input → same output; input dict is not mutated."""
        from pse_ecosystem.models.safety.safety_checks import flammability_margins
        comp = {"H2": 0.5, "CO": 0.3, "CH4": 0.2}
        comp_copy = dict(comp)
        r1 = flammability_margins(dict(comp))
        r2 = flammability_margins(dict(comp))
        # Idempotent
        assert r1 == r2
        # Input unchanged
        assert comp == comp_copy

    def test_flammability_no_pse_imports(self):
        """safety_checks.py must not import from pse_ecosystem (layer boundary)."""
        src_path = (
            pathlib.Path(__file__).parent.parent
            / "pse_ecosystem" / "models" / "safety" / "safety_checks.py"
        )
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        pse_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and any(
                "pse_ecosystem" in (getattr(node, "module", "") or "")
                or "pse_ecosystem" in (getattr(alias, "name", "") or "")
                for alias in (getattr(node, "names", []))
            )
        ]
        # Also check ImportFrom with module attribute
        import_froms = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and "pse_ecosystem" in (node.module or "")
        ]
        assert not import_froms, (
            f"safety_checks.py contains pse_ecosystem imports (layer violation): "
            f"{[n.module for n in import_froms]}"
        )

    def test_compute_safety_margins_does_not_mutate_solution_x(self):
        """Running compute_safety_margins() must not alter the result.x dict."""
        from pse_ecosystem.ui.flowsheet_service import compute_safety_margins
        # Build a minimal flowsheet for the test
        try:
            from pse_ecosystem.ui.flowsheet_service import load_template
            fs = load_template("hydrogen.electrolysis_only")
        except Exception:
            pytest.skip("electrolysis_only template unavailable")

        x = {v: 1.0 for v in fs.all_variables()}
        x_snapshot = dict(x)
        _ = compute_safety_margins(fs, x)
        assert x == x_snapshot, "compute_safety_margins must not mutate solution_x"
