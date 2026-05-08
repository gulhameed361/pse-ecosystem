"""Data layer: weather profiles, demand time-series, site data.

This layer is independent of the Handshake Protocol — it does not produce
LinearizedModel objects and is never called by the SLP driver directly.
Its outputs (numpy arrays of GHI, wind speed, price profiles) are consumed
by flowsheet factories that construct time-indexed optimisation problems.
"""
