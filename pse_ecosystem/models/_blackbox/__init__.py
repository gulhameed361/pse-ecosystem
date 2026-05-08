"""Private black-box simulator sources.

These modules contain the raw simulation functions (ODE integrators, VLE solvers,
shortcut column methods) extracted from the Extra/ folder. They are internal
implementation details — import the public BaseUnit wrappers in models/reactor/,
models/separator/, and models/distillation/ instead.
"""
