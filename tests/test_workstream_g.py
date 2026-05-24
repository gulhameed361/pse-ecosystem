"""v1.6 Workstream G — Industrial Mode unit-picker filter tests.

Coverage:
* G.1 ``available_units_for_persona`` — Academic returns everything,
  Industrial hides DIDACTIC + LEGACY, ``show_screening=False`` also hides
  the FUG shortcut.
* G.1 ``unit_categories_for_persona`` — empty categories pruned.
* G.2 All 10 Workstream B units now appear in ``AVAILABLE_UNITS``.
* G.3 Back-compat invariants — every label in UNIT_CATEGORIES is a key
  in AVAILABLE_UNITS, and every key in AVAILABLE_UNITS appears in at
  least one UNIT_CATEGORIES section.
"""

from __future__ import annotations

import pytest

from pse_ecosystem.models.base_unit import UnitCategory
from pse_ecosystem.ui.flowsheet_service import (
    AVAILABLE_UNITS,
    UNIT_CATEGORIES,
    available_units_for_persona,
    unit_categories_for_persona,
)


# ─────────────────────────────────────────────────────────────────────────────
# G.2 — new units registered
# ─────────────────────────────────────────────────────────────────────────────


class TestNewUnitsInCatalogue:
    @pytest.mark.parametrize(
        "label",
        [
            "ExpanderHF",
            "MultistageCompressorHF",
            "DecanterHF",
            "SteamDrumHF",
            "FiredHeaterHF",
            "PackedColumnHF",
            "MembraneModuleHF",
            "BatchReactorHF",
            "TrayColumnHF",
            "CrystallizerHF",
        ],
    )
    def test_label_in_available_units(self, label):
        assert label in AVAILABLE_UNITS

    @pytest.mark.parametrize(
        "label",
        [
            "ExpanderHF",
            "MultistageCompressorHF",
            "DecanterHF",
            "SteamDrumHF",
            "FiredHeaterHF",
            "PackedColumnHF",
            "MembraneModuleHF",
            "BatchReactorHF",
            "TrayColumnHF",
            "CrystallizerHF",
        ],
    )
    def test_label_in_unit_categories(self, label):
        all_labels = {lbl for grp in UNIT_CATEGORIES.values() for lbl in grp}
        assert label in all_labels


# ─────────────────────────────────────────────────────────────────────────────
# G.1 — Industrial Mode filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPersonaFilter:
    def test_academic_returns_everything(self):
        # Academic preserves v1.5.x behaviour — every unit is visible.
        filtered = available_units_for_persona("Academic")
        assert filtered == AVAILABLE_UNITS

    def test_industrial_hides_didactic(self):
        # PEMToy is DIDACTIC; must be hidden in Industrial mode.
        filtered = available_units_for_persona("Industrial")
        assert "PEMToy" not in filtered
        assert "GasifierToy" not in filtered

    def test_industrial_keeps_industrial(self):
        filtered = available_units_for_persona("Industrial")
        # Spot-check INDUSTRIAL units stay visible.
        for label in ("CSTRHF", "FlashVLHF", "TrayColumnHF", "ExpanderHF"):
            if label in AVAILABLE_UNITS:
                assert label in filtered

    def test_industrial_keeps_screening_by_default(self):
        # DistillationHF is SCREENING — default keeps it visible (with badge).
        filtered = available_units_for_persona("Industrial")
        assert "DistillationHF" in filtered

    def test_industrial_no_screening_drops_fug(self):
        # show_screening=False removes the FUG shortcut for industrial-only.
        filtered = available_units_for_persona(
            "Industrial", show_screening=False,
        )
        assert "DistillationHF" not in filtered

    def test_unknown_persona_is_academic(self):
        # Unrecognised persona falls back to Academic / show-all.
        filtered = available_units_for_persona("Consultant")
        assert filtered == AVAILABLE_UNITS

    def test_returns_fresh_dict_no_mutation(self):
        # Mutating the returned dict must not affect AVAILABLE_UNITS.
        baseline_n = len(AVAILABLE_UNITS)
        f = available_units_for_persona("Academic")
        f["__test_label__"] = "should not leak"
        assert len(AVAILABLE_UNITS) == baseline_n


class TestUnitCategoriesPersona:
    def test_academic_unchanged(self):
        academic = unit_categories_for_persona("Academic")
        # All categories preserved.
        for grp in UNIT_CATEGORIES:
            assert grp in academic
            assert academic[grp] == UNIT_CATEGORIES[grp]

    def test_industrial_drops_didactic_from_feed_product(self):
        industrial = unit_categories_for_persona("Industrial")
        # "Feed/Product" only contained PEMToy / GasifierToy — both DIDACTIC.
        # That category should disappear (or be reduced) in Industrial mode.
        if "Feed/Product" in industrial:
            assert "PEMToy" not in industrial["Feed/Product"]
            assert "GasifierToy" not in industrial["Feed/Product"]
        # The category may be absent if it became empty.
        assert industrial.get("Feed/Product", []) == []

    def test_industrial_keeps_reactors(self):
        industrial = unit_categories_for_persona("Industrial")
        assert "Reactors" in industrial
        assert "BatchReactorHF" in industrial["Reactors"]


# ─────────────────────────────────────────────────────────────────────────────
# G.3 — Catalogue consistency invariants
# ─────────────────────────────────────────────────────────────────────────────


class TestCatalogueConsistency:
    def test_every_category_label_is_available(self):
        all_in_categories = {
            lbl for grp in UNIT_CATEGORIES.values() for lbl in grp
        }
        missing = all_in_categories - set(AVAILABLE_UNITS)
        assert not missing, (
            f"Labels appear in UNIT_CATEGORIES but not AVAILABLE_UNITS: "
            f"{missing}"
        )

    def test_every_available_unit_categorised(self):
        all_in_categories = {
            lbl for grp in UNIT_CATEGORIES.values() for lbl in grp
        }
        missing = set(AVAILABLE_UNITS) - all_in_categories
        assert not missing, (
            f"Labels appear in AVAILABLE_UNITS but no UNIT_CATEGORIES "
            f"section: {missing}"
        )
