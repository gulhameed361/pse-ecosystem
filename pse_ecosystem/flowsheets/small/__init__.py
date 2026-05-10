"""Pre-configured small flowsheet assemblies.

Each module in this package exports a factory function
``make_<name>(components, params) -> BaseFlowsheet`` that instantiates the
constituent units, wires ports via ``fs.connect()``, and returns a ready-to-
solve flowsheet.
"""
