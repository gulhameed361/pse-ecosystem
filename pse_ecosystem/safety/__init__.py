"""Process safety — relief sizing, depressuring, HAZOP node generation.

These modules are pure-Python and have no Layer 2 dependencies. They are
called post-solve from the UI / scripting layer to size pressure-relief
devices, run blowdown calculations, and emit HAZOP node lists.

Sub-modules
-----------
* ``relief_sizing``  — API 520 Part I orifice area + API 521 fire-case duty
* ``depressuring``   — Critical / sub-critical orifice flow + blowdown time
* ``hazop_nodes``    — Topology-based HAZOP node generator
"""
