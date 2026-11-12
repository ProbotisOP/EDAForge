"""Generate the demo files used by the golden-path test and for trying EDAForge by hand.

    python examples/demo/make_demo.py  [output-directory]

Writes three related files with patterns planted on purpose (seeded, so the files are identical
on every run):

* ``customers_us.csv`` and ``customers_eu.csv`` — the same columns, so they can be appended;
  the EU file records ``lifetime_value`` in cents instead of dollars (a cross-file unit
  mismatch), has a few inconsistent region labels and more missing ages.
* ``orders.xlsx`` — one row per order, joined to the customers by ``customer_id`` (many orders
  per customer). Contains duplicates, refunds stored as negative amounts, unknown customer IDs
  and a handful of extreme amounts.

Planted patterns (what an honest engine should be able to find, given enough data):

1. ``amount`` rises with ``discount_pct`` and then flattens (non-linear, saturating).
2. ``sessions_per_month`` vs ``satisfaction`` is positive overall but negative within every
   region (a reversal / Simpson's paradox).
3. ``promo`` is associated with ``amount`` only because loyal customers get more promotions and
   spend more; the association disappears after accounting for ``loyalty_years``.
4. Returns rise with ``delivery_days`` for new customers (``loyalty_years`` < 1) only.
5. ``amount`` steps up by about 18% from 2024-07-01 (a change point).

Everything else is noise. Nothing here is causal: the generator only creates associations.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

SEED = 20261110


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def make_demo(
    out: Path, seed: int = SEED, n_customers: int = 1500, n_orders: int = 7000
) -> list[Path]:
    import openpyxl

    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ customers
    regions = np.array(["North", "South", "East", "West"])
    region = rng.choice(regions, n_customers, p=[0.3, 0.25, 0.25, 0.2])
    plan = rng.choice(np.array(["basic", "plus", "pro"]), n_customers, p=[0.5, 0.3, 0.2])
    age = np.clip(rng.normal(42, 13, n_customers), 18, 85).round()
    loyalty = np.clip(rng.gamma(2.0, 1.6, n_customers), 0.05, 15).round(1)
    signup = [date(2024, 12, 31) - timedelta(days=int(y * 365.25)) for y in loyalty]
    region_mean = {"North": 4.0, "South": 8.0, "East": 12.0, "West": 16.0}
    mu = np.array([region_mean[r] for r in region])
    sessions = np.clip(mu + rng.normal(0, 2.5, n_customers), 0, None).round(1)
    satisfaction = np.clip(
        3 + 0.35 * mu - 0.30 * (sessions - mu) + rng.normal(0, 0.9, n_customers), 0, 10
    ).round(1)
    plan_bonus = np.select([plan == "plus", plan == "pro"], [150.0, 400.0], 0.0)
    ltv = (200 + 150 * loyalty + plan_bonus + rng.normal(0, 60, n_customers)).round(2)
    newsletter = rng.choice(np.array(["yes", "no"]), n_customers, p=[0.4, 0.6])
    market = rng.choice(np.array(["US", "EU"]), n_customers, p=[0.6, 0.4])
    ids = np.array([f"C{i:05d}" for i in range(1, n_customers + 1)])

    customers = pl.DataFrame(
        {
            "customer_id": ids,
            "signup_date": signup,
            "region": region,
            "plan": plan,
            "age": age,
            "loyalty_years": loyalty,
            "sessions_per_month": sessions,
            "satisfaction": satisfaction,
            "lifetime_value": ltv,
            "newsletter": newsletter,
            "email": [f"user{i}@example.com" for i in range(1, n_customers + 1)],
            "market": market,
        }
    )
    us = customers.filter(pl.col("market") == "US").drop("market")
    eu = customers.filter(pl.col("market") == "EU").drop("market")
    # EU quirks: cents instead of dollars, inconsistent labels, more missing ages.
    eu = eu.with_columns((pl.col("lifetime_value") * 100).round(0).alias("lifetime_value"))
    eu_rng = np.random.default_rng(seed + 1)
    messy = eu_rng.random(eu.height) < 0.03
    eu = eu.with_columns(
        pl.when(pl.Series(messy))
        .then(pl.col("region").str.to_lowercase())
        .otherwise(pl.col("region"))
        .alias("region"),
        pl.when(pl.Series(eu_rng.random(eu.height) < 0.10))
        .then(None)
        .otherwise(pl.col("age"))
        .alias("age"),
    )
    us = us.with_columns(
        pl.when(pl.Series(np.random.default_rng(seed + 2).random(us.height) < 0.03))
        .then(None)
        .otherwise(pl.col("age"))
        .alias("age")
    )
    paths = [out / "customers_us.csv", out / "customers_eu.csv"]
    us.write_csv(paths[0])
    eu.write_csv(paths[1])

    # ------------------------------------------------------------------ orders
    weights = (1.0 + loyalty) / (1.0 + loyalty).sum()
    who = rng.choice(n_customers, n_orders, p=weights)
    start = date(2024, 1, 1)
    day = rng.integers(0, 366, n_orders)
    order_date = [start + timedelta(days=int(d)) for d in day]
    discount = rng.choice(np.arange(0, 45, 5), n_orders)
    promo = rng.random(n_orders) < _sigmoid(-1.6 + 0.45 * loyalty[who])
    plan_effect = np.select([plan[who] == "plus", plan[who] == "pro"], [10.0, 25.0], 0.0)
    amount = (
        40
        + 9 * loyalty[who]
        + plan_effect
        + 55 * (1 - np.exp(-discount / 9.0))
        + rng.normal(0, 12, n_orders)
    )
    after = np.array([d >= date(2024, 7, 1) for d in order_date])
    amount = np.where(after, amount * 1.18, amount)
    delivery = rng.integers(1, 15, n_orders)
    new = loyalty[who] < 1.0
    p_return = _sigmoid(-2.8 + np.where(new, 0.30, 0.02) * delivery)
    returned = (rng.random(n_orders) < p_return).astype(int)
    channel = rng.choice(np.array(["web", "app", "store"]), n_orders, p=[0.5, 0.3, 0.2])
    extreme = rng.choice(n_orders, 10, replace=False)
    amount[extreme] *= 25
    refunds = rng.choice(np.setdiff1d(np.arange(n_orders), extreme), 3, replace=False)
    amount[refunds] *= -1
    customer_ref = ids[who].copy()
    unknown = rng.choice(n_orders, 15, replace=False)
    customer_ref[unknown] = [f"C9{i:04d}" for i in range(15)]

    rows = list(
        zip(
            [f"O{i:06d}" for i in range(1, n_orders + 1)],
            customer_ref.tolist(),
            order_date,
            amount.round(2).tolist(),
            discount.tolist(),
            delivery.tolist(),
            promo.tolist(),
            returned.tolist(),
            channel.tolist(),
            strict=True,
        )
    )
    rows += [rows[int(i)] for i in rng.choice(n_orders, 6, replace=False)]  # exact duplicates
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Orders"
    sheet.append(
        [
            "order_id",
            "customer_id",
            "order_date",
            "amount",
            "discount_pct",
            "delivery_days",
            "promo",
            "returned",
            "channel",
        ]
    )
    for row in rows:
        sheet.append(list(row))
    paths.append(out / "orders.xlsx")
    workbook.save(paths[-1])
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo-data")
    for path in make_demo(target):
        print(path)
