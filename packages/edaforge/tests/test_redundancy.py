"""Near-copy columns are clustered and merged in the feed.

The rare-label threshold is a setting.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from edaforge.discovery.redundancy import find_redundant
from edaforge.discovery.run import RunSettings


def _frame(n: int = 400, seed: int = 3) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    price = rng.lognormal(3, 0.5, n)
    region = rng.choice(["north", "south", "east"], n)
    return pl.DataFrame(
        {
            "price": price,
            "price_eur": price * 0.92 + rng.normal(0, 0.01, n),  # a copy in another currency
            "price_rank": -np.argsort(np.argsort(price)).astype(float),  # perfectly reversed order
            "qty": rng.poisson(5, n).astype(float),  # independent
            "region": region,
            "region_code": [{"north": "N", "south": "S", "east": "E"}[r] for r in region],
            "segment": rng.choice(["a", "b", "c"], n),  # independent of region
        }
    )


def test_numeric_and_label_copies_are_clustered() -> None:
    f = _frame()
    aliases, notes = find_redundant(
        f, ["price", "price_eur", "price_rank", "qty"], ["region", "region_code", "segment"]
    )
    assert aliases == {"price_eur": "price", "price_rank": "price", "region_code": "region"}
    assert len(notes) == 2
    assert "ρ" in notes[0]


def test_independent_columns_are_never_merged() -> None:
    rng = np.random.default_rng(0)
    for _ in range(20):
        x = rng.normal(size=200)
        f = pl.DataFrame(
            {"a": x, "b": 0.8 * x + rng.normal(0, 0.6, 200), "c": rng.normal(size=200)}
        )
        aliases, _ = find_redundant(f, ["a", "b", "c"], [])
        assert (
            aliases == {}
        )  # a strong but imperfect correlation (rho about 0.8) is a finding, not a copy


def test_too_few_rows_are_not_clustered() -> None:
    f = pl.DataFrame({"a": [1.0, 2.0, 3.0] * 5, "b": [1.0, 2.0, 3.0] * 5})
    assert find_redundant(f, ["a", "b"], [])[0] == {}


def test_min_group_size_defaults_to_10_and_cannot_go_lower() -> None:
    assert RunSettings().min_group_size == 10
    assert RunSettings(min_group_size=25).min_group_size == 25
    with pytest.raises(ValidationError):
        RunSettings(min_group_size=5)
