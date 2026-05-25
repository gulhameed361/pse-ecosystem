"""Unit factory + custom flowsheet assembler.

Three responsibilities:

* :func:`_instantiate_unit` — map a UI label string + parameter dict to a
  concrete :class:`BaseUnit` instance. Every entry in
  :data:`AVAILABLE_UNITS` has a corresponding branch here.
* :func:`build_custom_flowsheet` — assemble a :class:`BaseFlowsheet` from a
  ``{"units": [...], "connections": [...]}`` JSON config dict. Drives
  port wiring with the zero-fill padder fallback (v1.5.2) when component
  counts don't match.
* :func:`build_composite_unit` — wrap a built-in template as a
  :class:`CompositeUnit` so it can plug into a parent flowsheet as one
  atomic unit.

Extracted from ``flowsheet_service.py`` in v1.6.1 P.1.4 — see
``docs/PLAN_v1_6_1.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pse_ecosystem.ui.catalogue import AVAILABLE_UNITS
from pse_ecosystem.ui.port_resolver import _primary_inlet, _primary_outlet


def build_custom_flowsheet(config: Dict[str, Any]) -> "BaseFlowsheet":
    """Assemble a BaseFlowsheet from a user-defined unit + connection config.

    Parameters
    ----------
    config : dict with keys:
        ``"units"`` — list of dicts: {``"type"``: str, ``"id"``: str, ``"params"``: dict}
            Use ``"type": "__composite__"`` for pre-built CompositeUnit objects
            supplied via the ``"__composites__"`` key.
        ``"connections"`` — list of dicts: {``"from_unit"``: str, ``"to_unit"``: str}
            Each connection wires *from_unit*.outlet_port → *to_unit*.inlet_port.
        ``"__composites__"`` — optional dict mapping unit_id → pre-built CompositeUnit.

    Only unit types in :data:`AVAILABLE_UNITS` (or ``"__composite__"``) are accepted.
    """
    from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet

    composites: Dict[str, Any] = config.get("__composites__", {})
    unit_objects = []
    unit_map: Dict[str, Any] = {}

    for unit_cfg in config.get("units", []):
        utype = unit_cfg["type"]
        uid = unit_cfg["id"]
        params = unit_cfg.get("params", {})

        if utype == "__composite__":
            unit_obj = composites.get(uid)
            if unit_obj is None:
                raise ValueError(
                    f"Composite unit '{uid}' declared but not found in '__composites__' dict."
                )
        elif utype not in AVAILABLE_UNITS:
            raise ValueError(
                f"Unit type '{utype}' is not in the allowed list. "
                f"Choose from: {list(AVAILABLE_UNITS)}"
            )
        else:
            unit_obj = _instantiate_unit(utype, uid, params)

        unit_objects.append(unit_obj)
        unit_map[uid] = unit_obj

    fs = BaseFlowsheet(name="custom.user_flowsheet", units=unit_objects)

    conn_warnings: list = []
    for conn in config.get("connections", []):
        from_u = unit_map.get(conn["from_unit"])
        to_u = unit_map.get(conn["to_unit"])
        if from_u is None or to_u is None:
            continue
        out_port = _primary_outlet(from_u)
        in_port = _primary_inlet(to_u)
        if out_port is not None and in_port is not None:
            try:
                fs.connect(out_port, in_port,
                           description=f"{conn['from_unit']} → {conn['to_unit']}")
            except ValueError:
                # Variable-count mismatch (T/P flags differ or component counts differ).
                # Phase 1 — try flow-only pairing (F_ vars only on both ports).
                from pse_ecosystem.flowsheets.base_flowsheet import Connection as _Conn
                a_flows = [v for v in out_port.variable_names() if ".F_" in v]
                b_flows = [v for v in in_port.variable_names() if ".F_" in v]
                n_a, n_b = len(a_flows), len(b_flows)
                if n_a == n_b and a_flows:
                    # Same component count but T/P mismatch — exact flow-only link.
                    for va, vb in zip(a_flows, b_flows):
                        fs.connections.append(_Conn(
                            var_a=va, var_b=vb,
                            description=f"{conn['from_unit']} → {conn['to_unit']} (flow-only)",
                        ))
                elif n_a != n_b and (n_a > 0 or n_b > 0):
                    # Phase 2 — zero-fill padder: match by species name, zero-fill
                    # inlet vars that have no matching outlet, leave surplus outlet
                    # vars free.
                    a_map = {v.rsplit("F_", 1)[-1]: v for v in a_flows}
                    b_map = {v.rsplit("F_", 1)[-1]: v for v in b_flows}
                    matched = set(a_map) & set(b_map)
                    for sp in matched:
                        fs.connections.append(_Conn(
                            var_a=a_map[sp], var_b=b_map[sp],
                            description=(f"{conn['from_unit']} → {conn['to_unit']}"
                                         f" (padded:{sp})"),
                        ))
                    for sp in set(b_map) - matched:
                        fs.extra_equalities.append(({b_map[sp]: 1.0}, 0.0))
                    conn_warnings.append(
                        f"{conn['from_unit']} → {conn['to_unit']}: "
                        f"component count padded ({n_a} → {n_b}); "
                        f"{len(set(b_map) - matched)} inlet species zero-filled"
                    )
        elif out_port is None and in_port is None:
            conn_warnings.append(
                f"{conn['from_unit']} → {conn['to_unit']}: "
                "neither unit exposes outlet_port / inlet_port "
                "(toy units connect via KPI flow, not StreamPorts)"
            )

    fs._conn_warnings = conn_warnings
    return fs


def build_composite_unit(
    template_key: str,
    unit_id: str,
    exposed_inputs: List[str],
    exposed_outputs: List[str],
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Wrap a built-in template as a CompositeUnit for hierarchical flowsheet composition.

    The inner template is solved as a sub-problem during the outer SLP
    iteration. ``exposed_inputs`` / ``exposed_outputs`` are variable names
    from the inner flowsheet that the parent flowsheet can drive / read.
    """
    from pse_ecosystem.flowsheets.base_flowsheet import CompositeUnit

    # Deferred to break import cycle: ``load_template`` lives in
    # ``flowsheet_service`` for now (will move to ``templates.registry`` in P.1.5).
    from pse_ecosystem.ui.flowsheet_service import load_template

    inner_fs = load_template(template_key, params or {})
    return CompositeUnit(unit_id, inner_fs, exposed_inputs, exposed_outputs)


def _instantiate_unit(utype: str, uid: str, params: dict) -> Any:
    """Instantiate a unit by type name using safe deferred imports."""
    if utype == "PEMToy":
        from pse_ecosystem.models.electrolysis.pem_toy import PEMToy, PEMToyParams
        p = PEMToyParams(
            eta_kg_per_kWh=float(params.get("eta_kg_per_kWh", 0.018)),
            capacity_kW=float(params.get("capacity_kW", 10_000.0)),
            electricity_price_per_kWh=float(params.get("electricity_price_per_kWh", 0.05)),
            capex_annual_per_kW=float(params.get("capex_annual_per_kW", 100.0)),
            grid_carbon_intensity_kg_CO2_per_kWh=float(
                params.get("grid_carbon_intensity_kg_CO2_per_kWh", 0.233)
            ),
        )
        return PEMToy(uid, p)

    if utype == "GasifierToy":
        from pse_ecosystem.models.gasification.gasifier_toy import GasifierToy, GasifierToyParams
        p = GasifierToyParams(
            biomass_carbon_intensity_kg_CO2_per_kg=float(
                params.get("biomass_carbon_intensity_kg_CO2_per_kg", 0.03)
            ),
        )
        return GasifierToy(uid, p)

    if utype == "StoichiometricReactor":
        from pse_ecosystem.models.reactors.stoichiometric_reactor import (
            StoichiometricReactor, StoichiometricParams,
        )
        components = params.get("components", ["CO2", "H2", "methanol", "water"])
        stoich = params.get("stoichiometry", {"CO2": [-1.0], "H2": [-3.0],
                                               "methanol": [1.0], "water": [1.0]})
        sp = StoichiometricParams(
            stoichiometry={c: stoich.get(c, [0.0]) for c in components},
            xi_max=params.get("xi_max", None),
            feed_max=float(params.get("feed_max", 50.0)),
        )
        return StoichiometricReactor(uid, components, sp)

    if utype == "MixerHF":
        from pse_ecosystem.models.mixers.mixer_hf import MixerHF, MixerHFParams
        components = params.get("components", ["H2", "H2O"])
        mp = MixerHFParams(n_inlets=int(params.get("n_inlets", 2)))
        return MixerHF(uid, components, mp)

    if utype == "SeparatorHF":
        from pse_ecosystem.models.separators.separator_hf import SeparatorHF, SeparatorHFParams
        components = params.get("components", ["H2", "CO2"])
        n_out = int(params.get("n_outlets", 2))
        sf = params.get("split_fractions", None)
        sp = SeparatorHFParams(
            n_outlets=n_out,
            split_fractions=sf,
            feed_max=float(params.get("feed_max", 1e4)),
            T_min=float(params.get("T_min", 200.0)),
            T_max=float(params.get("T_max", 2000.0)),
            P_min=float(params.get("P_min", 1e3)),
            P_max=float(params.get("P_max", 1e7)),
        )
        return SeparatorHF(uid, components, sp)

    if utype == "FlashVLHF":
        from pse_ecosystem.models.separators.flash_vl_hf import FlashVLHF, FlashVLHFParams
        from pse_ecosystem.models.properties.vle import ANTOINE
        components = params.get("components", ["benzene", "toluene"])
        vle_species = [c for c in components if c in ANTOINE]
        if len(vle_species) < 2:
            vle_species = ["benzene", "toluene"]
            components = vle_species
        fp = FlashVLHFParams(
            species_vle=list(vle_species),
            feed_max=float(params.get("feed_max", 1e4)),
            T_min=float(params.get("T_min", 250.0)),
            T_max=float(params.get("T_max", 550.0)),
            P_min=float(params.get("P_min", 1e3)),
            P_max=float(params.get("P_max", 1e7)),
        )
        return FlashVLHF(uid, components, fp)

    if utype == "Compressor":
        from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams
        components = params.get("components", ["H2", "CO", "CO2"])
        cp = CompressorParams(
            eta_isentropic=float(params.get("eta_isentropic", 0.78)),
            P_out_Pa=float(params.get("P_out_Pa", 500_000.0)),
            feed_max=float(params.get("feed_max", 1e4)),
            T_min=float(params.get("T_min", 250.0)),
            T_max=float(params.get("T_max", 1500.0)),
            P_min=float(params.get("P_min", 1e4)),
            P_max=float(params.get("P_max", 1e8)),
            W_max=float(params.get("W_max", 1e9)),
            electricity_price_USD_per_kWh=float(params.get("electricity_price_USD_per_kWh", 0.05)),
        )
        return Compressor(uid, components, cp)

    if utype == "HeatExchangerNTU":
        from pse_ecosystem.models.heat_exchangers.heat_exchanger_ntu import (
            HeatExchangerNTU, HeatExchangerNTUParams,
        )
        shared = params.get("components", [])
        hot = params.get("hot_components", shared or ["H2", "CO"])
        cold = params.get("cold_components", ["H2O"])
        hp = HeatExchangerNTUParams(
            UA_W_per_K=float(params.get("UA_W_per_K", 5000.0)),
        )
        return HeatExchangerNTU(uid, hot, cold, hp)

    if utype == "TVSAContactor":
        from pse_ecosystem.models.dac.tvsa_contactor import TVSAContactor
        # y_co2_atm stored as ppm in UI, convert to mol fraction
        y_ppm = float(params.get("y_co2_atm", 415.0))
        y_frac = y_ppm * 1e-6 if y_ppm > 1.0 else y_ppm
        return TVSAContactor(
            uid,
            eta_cap=float(params.get("eta_cap", 0.85)),
            dP_fan_Pa=float(params.get("dP_fan_Pa", 200.0)),
            eta_fan=float(params.get("eta_fan", 0.75)),
            dH_des_kJ_per_mol=float(params.get("dH_des_kJ_per_mol", 70.0)),
            T_des_K=float(params.get("T_des_K", 393.0)),
            P_ads_kPa=float(params.get("P_ads_kPa", 101.325)),
            P_des_kPa=float(params.get("P_des_kPa", 5.0)),
            eta_vac=float(params.get("eta_vac", 0.70)),
            y_co2_atm=y_frac,
        )

    if utype == "ElectrolyserHF":
        from pse_ecosystem.models.dac.electrolyser_hf import ElectrolyserHF
        return ElectrolyserHF(
            uid,
            eta_elec=float(params.get("eta_elec", 0.70)),
            capex_USD_per_kW=float(params.get("capex_USD_per_kW", 1_200.0)),
        )

    if utype == "MethanationReactor":
        from pse_ecosystem.models.dac.methanation_reactor import MethanationReactor
        return MethanationReactor(
            uid, T_rx_K_default=float(params.get("T_rx_K", 673.0))
        )

    if utype == "CHPUnit":
        from pse_ecosystem.models.power.chp_unit import CHPUnit
        return CHPUnit(
            uid,
            eta_comb=float(params.get("eta_comb", 0.95)),
            eta_isentropic=float(params.get("eta_isentropic", 0.85)),
            eta_mechanical=float(params.get("eta_mechanical", 0.98)),
            eta_hrec=float(params.get("eta_hrec", 0.85)),
            lambda_air=float(params.get("lambda_air", 1.1)),
            fuel_feed_max=float(params.get("feed_max", 1e4)),
            T_fuel_min=float(params.get("T_min", 273.0)),
            T_fuel_max=float(params.get("T_max", 1500.0)),
            P_fuel_min=float(params.get("P_min", 1e4)),
            P_fuel_max=float(params.get("P_max", 5e6)),
            W_max=float(params.get("W_max", 1e9)),
        )

    if utype == "BiomassStorageHF":
        from pse_ecosystem.models.biomass.biomass_storage import BiomassStorageHF
        return BiomassStorageHF(
            uid,
            biomass_type=params.get("biomass_type", "Pine Wood"),
            T_in_C=float(params.get("T_in_C", 15.0)),
            T_preheat_C=float(params.get("T_preheat_C", 200.0)),
        )

    if utype == "BiomassGasifierHF":
        from pse_ecosystem.models.biomass.biomass_gasifier import BiomassGasifierHF
        return BiomassGasifierHF(
            uid,
            biomass_type=params.get("biomass_type", "Pine Wood"),
            T_gasifier_C=float(params.get("T_gasifier_C", 800.0)),
            gasifying_agent=params.get("gasifying_agent", "Steam"),
            P_atm=float(params.get("P_atm", 1.0)),
            biomass_cost_USD_per_kg=float(params.get("biomass_cost_USD_per_kg", 0.05)),
        )

    if utype == "WGSReactorHF":
        from pse_ecosystem.models.biomass.wgs_reactor import WGSReactorHF
        return WGSReactorHF(
            uid,
            T_wgs_C=float(params.get("T_wgs_C", 400.0)),
            feed_max=float(params.get("feed_max", 1e4)),
        )

    if utype == "CoolerHF":
        from pse_ecosystem.models.heat_exchangers.cooler_hf import CoolerHF, CoolerHFParams
        components = params.get("components", ["H2", "CO", "CO2", "H2O", "CH4", "N2"])
        cp = CoolerHFParams(
            T_out_K=float(params.get("T_out_K", 400.0)),
            feed_max=float(params.get("feed_max", 1_000.0)),
            T_min=float(params.get("T_min", 200.0)),
            T_max=float(params.get("T_max", 2000.0)),
            P_min=float(params.get("P_min", 1e3)),
            P_max=float(params.get("P_max", 1e8)),
            Q_max_kW=float(params.get("Q_max_kW", 1e7)),
            cooling_water_price_USD_per_GJ=float(
                params.get("cooling_water_price_USD_per_GJ", 0.35)
            ),
        )
        return CoolerHF(uid, components, cp)

    # ── v1.4.0 audit H11: newly registered UI types ──────────────────────────
    if utype == "Pump":
        from pse_ecosystem.models.pressure_changers.pump import Pump, PumpParams
        components = params.get("components", ["H2O"])
        p_out = params.get("P_out_Pa", 1_000_000.0)
        pp = PumpParams(
            eta_pump=float(params.get("eta_pump", 0.75)),
            density_kg_m3=float(params.get("density_kg_m3", 1000.0)),
            molar_mass_kg_mol=float(params.get("molar_mass_kg_mol", 0.018)),
            P_out_Pa=float(p_out) if p_out else None,
            feed_max=float(params.get("feed_max", 1e4)),
            T_min=float(params.get("T_min", 250.0)),
            T_max=float(params.get("T_max", 600.0)),
            P_min=float(params.get("P_min", 1e3)),
            P_max=float(params.get("P_max", 1e8)),
            W_max=float(params.get("W_max", 1e9)),
            electricity_price_USD_per_kWh=float(params.get("electricity_price_USD_per_kWh", 0.05)),
        )
        return Pump(uid, components, pp)

    if utype == "Valve":
        from pse_ecosystem.models.pressure_changers.valve import Valve, ValveParams
        components = params.get("components", ["H2", "CO", "CO2"])
        cv_val = params.get("Cv", None)
        p_out = params.get("P_out_Pa", None)
        vp = ValveParams(
            Cv=float(cv_val) if cv_val not in (None, 0.0) else None,
            P_out_Pa=float(p_out) if p_out not in (None, 0.0) else None,
        )
        return Valve(uid, components, vp)

    if utype == "ShellTubeHX":
        from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeHX, ShellTubeParams
        shared = params.get("components", [])
        hot = params.get("hot_components", shared or ["H2", "CO"])
        cold = params.get("cold_components", ["H2O"])
        sp = ShellTubeParams(
            U_W_per_m2_K=float(params.get("U_W_per_m2_K", 500.0)),
            A_m2=float(params.get("A_m2", 16.0)),
            n_shell_passes=int(params.get("n_shell_passes", 1)),
            n_tube_passes=int(params.get("n_tube_passes", 2)),
        )
        return ShellTubeHX(uid, hot, cold, sp)

    if utype == "H2SeparatorPSA":
        from pse_ecosystem.models.biomass.h2_separator import H2SeparatorPSA
        return H2SeparatorPSA(
            uid,
            H2_recovery=float(params.get("H2_recovery", 0.85)),
            electricity_price_USD_per_kWh=float(params.get("electricity_price_USD_per_kWh", 0.05)),
            feed_max=float(params.get("feed_max", 1e4)),
        )

    if utype == "GibbsReactor":
        from pse_ecosystem.models.reactors.gibbs_reactor import GibbsReactor, GibbsReactorParams
        components = params.get("components", ["H2", "CO", "CO2", "H2O"])
        gp = GibbsReactorParams(T_max=float(params.get("T_max", 2000.0)))
        return GibbsReactor(uid, components, gp)

    if utype == "EquilibriumReactor":
        from pse_ecosystem.models.reactors.equilibrium_reactor import (
            EquilibriumReactor, EquilReactorParams,
        )
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        components = params.get("components", ["CO", "H2O", "CO2", "H2"])
        # Default reaction set is WGS (CO + H₂O ↔ CO₂ + H₂). ReactionConfig
        # carries kinetic fields (k0, Ea, orders) that the equilibrium driver
        # ignores; we still have to fill them. Override by passing a full
        # `reactions` list through the Python API.
        default_rxn = ReactionConfig(
            stoichiometry={"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0},
            k0=1.0,
            Ea_J_per_mol=0.0,
            reaction_orders={"CO": 1.0, "H2O": 1.0},
            delta_H_J_per_mol=-41_200.0,
            name="WGS",
        )
        ep = EquilReactorParams(
            reactions=params.get("reactions", [default_rxn]),
            Keq_ref=params.get("Keq_ref_list", [float(params.get("Keq_ref", 8.9))]),
            T_ref_K=float(params.get("T_ref_K", 673.0)),
        )
        return EquilibriumReactor(uid, components, ep)

    if utype == "DistillationHF":
        from pse_ecosystem.models.separators.distillation_hf import (
            DistillationHF, DistillationHFParams,
        )
        from pse_ecosystem.models.properties.vle import ANTOINE
        components = params.get("components", ["benzene", "toluene"])
        vle_species = [c for c in components if c in ANTOINE]
        if len(vle_species) < 2:
            vle_species = ["benzene", "toluene"]
            components = vle_species
        hk = params.get("hk", "toluene")
        lk = params.get("lk", "benzene")
        # v1.4.0 audit N20 — pre-fix this silently rewrote user-selected
        # hk/lk to the first/last VLE species when they were missing from
        # the component list. The user's intent was lost. Now we raise so
        # the caller knows the mismatch and can pass valid keys.
        if hk not in components:
            raise ValueError(
                f"DistillationHF heavy key {hk!r} not in components "
                f"{components!r}. Pass a 'hk' that names one of the unit's "
                f"declared species."
            )
        if lk not in components:
            raise ValueError(
                f"DistillationHF light key {lk!r} not in components "
                f"{components!r}. Pass a 'lk' that names one of the unit's "
                f"declared species."
            )
        dp = DistillationHFParams(
            species_vle=vle_species,
            lk=lk,
            hk=hk,
            T_op_K=float(params.get("T_op_K", 350.0)),
            R_over_Rmin=float(params.get("R_over_Rmin", 1.3)),
        )
        return DistillationHF(uid, components, dp)

    # ── v1.6 Workstream B — new industrial units ────────────────────────────
    if utype == "ExpanderHF":
        from pse_ecosystem.models.pressure_changers.expander import (
            ExpanderHF, ExpanderParams,
        )
        comps = params.get("components", ["N2"])
        return ExpanderHF(uid, comps, ExpanderParams())

    if utype == "MultistageCompressorHF":
        from pse_ecosystem.models.pressure_changers.multistage_compressor import (
            MultistageCompressorHF, MultistageCompressorHFParams,
        )
        comps = params.get("components", ["N2", "H2O"])
        return MultistageCompressorHF(uid, comps, MultistageCompressorHFParams())

    if utype == "DecanterHF":
        from pse_ecosystem.models.separators.decanter import (
            DecanterHF, DecanterHFParams,
        )
        comps = params.get("components", ["A", "B"])
        return DecanterHF(uid, comps, DecanterHFParams())

    if utype == "SteamDrumHF":
        from pse_ecosystem.models.utilities.steam_drum import (
            SteamDrumHF, SteamDrumHFParams,
        )
        return SteamDrumHF(uid, SteamDrumHFParams())

    if utype == "FiredHeaterHF":
        from pse_ecosystem.models.heat_exchangers.fired_heater import (
            FiredHeaterHF, FiredHeaterHFParams,
        )
        proc_comps = params.get("process_components", ["N2"])
        return FiredHeaterHF(uid, proc_comps, FiredHeaterHFParams())

    if utype == "PackedColumnHF":
        from pse_ecosystem.models.separators.packed_column import (
            PackedColumnHF, PackedColumnHFParams,
        )
        gas = params.get("gas_components", ["CO2", "N2"])
        liq = params.get("liquid_components", ["CO2", "H2O"])
        return PackedColumnHF(uid, gas, liq, PackedColumnHFParams(solute="CO2"))

    if utype == "MembraneModuleHF":
        from pse_ecosystem.models.separators.membrane_module import (
            MembraneModuleHF, MembraneModuleHFParams,
        )
        comps = params.get("components", ["H2", "CO2"])
        return MembraneModuleHF(uid, comps, MembraneModuleHFParams())

    if utype == "BatchReactorHF":
        from pse_ecosystem.models.reactors.batch_reactor import (
            BatchReactorHF, BatchReactorHFParams,
        )
        from pse_ecosystem.models.reactors.cstr_hf import ReactionConfig
        comps = params.get("components", ["A", "B"])
        # Smoke-test default: trivial 1-reaction A → B kinetics.
        default_rxn = ReactionConfig(
            stoichiometry={"A": -1.0, "B": 1.0},
            k0=1.0e6, Ea_J_per_mol=80_000.0,
            reaction_orders={"A": 1.0},
        )
        return BatchReactorHF(
            uid, comps,
            BatchReactorHFParams(reactions=[default_rxn]),
        )

    if utype == "TrayColumnHF":
        from pse_ecosystem.models.separators.tray_column import (
            TrayColumnHF, TrayColumnHFParams,
        )
        comps = params.get("components", ["benzene", "toluene"])
        return TrayColumnHF(
            uid, comps,
            TrayColumnHFParams(
                light_key=params.get("lk", comps[0]),
                heavy_key=params.get("hk", comps[-1]),
                species_vle=comps,
            ),
        )

    if utype == "CrystallizerHF":
        from pse_ecosystem.models.separators.crystallizer import (
            CrystallizerHF, CrystallizerHFParams,
        )
        return CrystallizerHF(uid, CrystallizerHFParams())

    raise ValueError(f"Unknown unit type: {utype}")


__all__ = [
    "build_custom_flowsheet",
    "build_composite_unit",
    "_instantiate_unit",
]
