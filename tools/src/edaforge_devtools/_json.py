"""Typed narrowing for parsed JSON and TOML (keeps strict type checking honest)."""

from __future__ import annotations

from typing import cast

__all__ = ["as_dict", "as_list", "as_str"]


def as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return {str(k): v for k, v in cast("dict[object, object]", value).items()}
    return None


def as_list(value: object) -> list[object] | None:
    if isinstance(value, list):
        return list(cast("list[object]", value))
    return None


def as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default
