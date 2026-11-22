"""Safety pattern data sub-package (source of truth).

Canonical location for all safety rule data. Each submodule defines a
module-level list of ``(regex, label)`` 2-tuples. Re-exported here so that
``from tuan_cli.ext.patterns_data import _CRITICAL_PATTERNS, ...`` works
and so that ``safety_patterns.py`` can act as a thin compat re-export layer.
"""
from .critical import _CRITICAL_PATTERNS, _RAW_DISK
from .extreme import _EXTREME_PATTERNS
from .high import _HIGH_PATTERNS
from .medium import _MEDIUM_PATTERNS

__all__ = [
    "_CRITICAL_PATTERNS",
    "_EXTREME_PATTERNS",
    "_HIGH_PATTERNS",
    "_MEDIUM_PATTERNS",
    "_RAW_DISK",
]
