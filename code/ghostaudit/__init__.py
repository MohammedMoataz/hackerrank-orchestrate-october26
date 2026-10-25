"""Ghost Data Still Exists: a deterministic deletion-audit agent.

The package reads the participant dataset, reconstructs each deletion request's true state at its
audit cutoff from evidence files, applies the deletion policy and writes ordered remediation plans.
No model is called at runtime; every decision is made by the code in this package.
"""
