"""License gate (section 13.3): Python, npm and model-weight license checks for CI."""

from edaforge_devtools.license_gate.classify import Decision, Verdict, classify_expression
from edaforge_devtools.license_gate.policy import Policy, load_policy

__all__ = ["Decision", "Policy", "Verdict", "classify_expression", "load_policy"]
