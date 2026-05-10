"""Small flowsheet: Feed → Compressor → Shell & Tube HX → Valve.

Use case: gas compression with intercooling then let-down expansion
(e.g., compressed natural gas supply network segment).

Factory
-------
make_compression_train(components, P_compressed_Pa,
                        hx_params, comp_params, valve_params) -> BaseFlowsheet
"""

from __future__ import annotations

from typing import List, Optional

from pse_ecosystem.flowsheets.base_flowsheet import BaseFlowsheet
from pse_ecosystem.models.pressure_changers.compressor import Compressor, CompressorParams
from pse_ecosystem.models.heat_exchangers.shell_tube import ShellTubeHX, ShellTubeParams
from pse_ecosystem.models.pressure_changers.valve import Valve, ValveParams


def make_compression_train(
    hot_components: List[str],
    cold_components: List[str],
    P_compressed_Pa: float = 500_000.0,
    comp_params: Optional[CompressorParams] = None,
    hx_params: Optional[ShellTubeParams] = None,
    valve_params: Optional[ValveParams] = None,
) -> BaseFlowsheet:
    """Create a Compressor → Shell&Tube HX → Valve flowsheet.

    The hot side of the HX is the compressed gas; cold side is a utility
    coolant stream (cold_components).  After cooling, gas is let down via
    the valve.

    Parameters
    ----------
    hot_components  : Gas components flowing through the compressor.
    cold_components : Coolant-side components for the HX.
    P_compressed_Pa : Compressor outlet / HX inlet pressure [Pa].
    """
    if comp_params is None:
        comp_params = CompressorParams(P_out_Pa=P_compressed_Pa)
    if hx_params is None:
        hx_params = ShellTubeParams(U_W_per_m2_K=500.0, A_m2=10.0)
    if valve_params is None:
        valve_params = ValveParams()

    comp  = Compressor("comp", hot_components, comp_params)
    hx    = ShellTubeHX("hx", hot_components, cold_components, hx_params)
    valve = Valve("valve", hot_components, valve_params)

    fs = BaseFlowsheet(
        name="small.compression_train",
        units=[comp, hx, valve],
    )
    fs.connect(comp.outlet_port,    hx.hot_inlet_port,  description="Compressor → HX hot side")
    fs.connect(hx.hot_outlet_port,  valve.inlet_port,   description="HX hot out → Valve")
    return fs
