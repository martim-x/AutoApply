"""Merge missing config keys with documented defaults + UI notifications."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConfigLoadResult:
    """Result of loading a config file with soft defaults."""

    data: dict[str, Any]
    notifications: list[str] = field(default_factory=list)
    used_defaults: bool = False
    source: str = ""  # path or "defaults" / "example"


def deep_merge_defaults(
    raw: dict[str, Any] | None,
    defaults: dict[str, Any],
    *,
    prefix: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """
    Fill missing keys from defaults. Existing keys win.
    Returns (merged, notification messages).
    """
    notes: list[str] = []
    base = deepcopy(defaults)
    if not raw:
        notes.append(
            f"using full defaults{f' for {prefix}' if prefix else ''} because config missing"
        )
        return base, notes

    def _merge(dst: dict[str, Any], src: dict[str, Any], path: str) -> None:
        for key, default_val in src.items():
            loc = f"{path}.{key}" if path else key
            if key not in dst or dst[key] is None:
                dst[key] = deepcopy(default_val)
                notes.append(f"using default {loc}={_fmt(default_val)} because missing")
            elif isinstance(default_val, dict) and isinstance(dst[key], dict):
                _merge(dst[key], default_val, loc)
            elif isinstance(default_val, list) and (
                not isinstance(dst[key], list) or len(dst[key]) == 0
            ):
                dst[key] = deepcopy(default_val)
                notes.append(f"using default {loc} because empty/invalid")

    out = deepcopy(raw)
    _merge(out, base, prefix)
    return out, notes


def _fmt(v: Any) -> str:
    if isinstance(v, list):
        if len(v) <= 3:
            return repr(v)
        return f"[{len(v)} items]"
    if isinstance(v, dict):
        return "{…}"
    s = repr(v)
    return s if len(s) < 80 else s[:77] + "…"
