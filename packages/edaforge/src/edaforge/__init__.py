"""EDAForge: local-first, statistically rigorous multi-file pattern discovery.

The engine finds patterns with a measured false-alarm rate; it does not find every pattern, and
it does not prove causation. See docs/PROJECT_PROMPT.md.
"""

from __future__ import annotations

from edaforge.api import Run, discover, load_run, reproduce_from_directory
from edaforge.config import EDAForgeConfig, load_config
from edaforge.runtime.manifest import edaforge_version

__all__ = [
    "EDAForgeConfig",
    "Run",
    "__version__",
    "discover",
    "load_config",
    "load_run",
    "reproduce_from_directory",
]

__version__ = edaforge_version()
