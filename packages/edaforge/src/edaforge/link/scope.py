"""Discovery scope: analyze one file, or several files connected into one table.

:func:`plan_scope` proposes how the chosen tables connect, using the same suggestions and
safety checks as the Connect page, and previews every step before anything is built:

1. appends first (files with the same columns are stacked, keeping ``__source__``);
2. then joins onto the largest table (the most detailed one, such as orders), one table at a time,
   choosing the most confident many-to-one or one-to-one link;
3. a table that connects to nothing is reported with the reason and left out; it is never forced
   in.

Nothing is joined silently: the plan lists each step's row counts, warnings and the points the
user must acknowledge, and :func:`build_scope` refuses to build a step that needs an
acknowledgement the user did not give.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from edaforge.link import (
    BuiltLink,
    LinkError,
    LinkSpec,
    LinkSuggestion,
    Table,
    build_link,
    suggest_links,
)

__all__ = ["ScopePlan", "ScopeStep", "build_scope", "plan_scope"]


class ScopeStep(BaseModel):
    spec: LinkSpec
    left_name: str
    right_name: str
    kind: str
    confidence: float
    reasons: list[str] = []
    n_left: int
    n_right: int
    n_result: int
    row_multiplication: float
    warnings: list[dict[str, str]] = []
    requires_ack: bool = False
    ack_reasons: list[str] = []
    result_name: str


class ScopePlan(BaseModel):
    tables: list[str]
    steps: list[ScopeStep] = []
    unconnected: list[dict[str, str]] = []
    relations: list[dict[str, Any]] = []  # every pairwise relationship found among the chosen files
    result_rows: int = 0
    result_name: str = ""
    requires_ack: bool = False
    columns: list[dict[str, Any]] = []  # the connected table's columns (name, role, pii)


@dataclass
class _Built:
    table: Table
    steps: list[tuple[ScopeStep, BuiltLink]] = field(
        default_factory=list[tuple[ScopeStep, BuiltLink]]
    )


def _best(
    suggestions: list[LinkSuggestion], kinds: set[str], base: str | None = None
) -> LinkSuggestion | None:
    usable = [
        s
        for s in suggestions
        if s.kind in kinds
        and s.spec is not None
        and (base is None or base in {s.left, s.right})
        and (s.kind == "append" or s.cardinality in {"m:1", "1:1", "1:m"})
    ]
    return max(usable, key=lambda s: s.confidence, default=None)


def _spec(s: LinkSuggestion) -> LinkSpec:
    """The suggestion's link specification (``_best`` only returns suggestions that have one)."""
    if s.spec is None:
        msg = f"the suggested link between {s.left} and {s.right} has no specification"
        raise LinkError(msg)
    return s.spec


def _orient(s: LinkSuggestion, base: str) -> LinkSpec:
    """Put ``base`` on the left of a join so its rows are kept one-for-one."""
    spec = _spec(s)
    if spec.left == base:
        return spec
    return spec.model_copy(
        update={
            "left": spec.right,
            "right": spec.left,
            "keys": [k.model_copy(update={"left": k.right, "right": k.left}) for k in spec.keys],
        }
    )


def _relations(tables: Sequence[Table]) -> list[dict[str, Any]]:
    names = {t.id: t.name for t in tables}
    return [
        {
            "left": names[s.left],
            "right": names[s.right],
            "kind": s.kind,
            "confidence": s.confidence,
            "keys": [f"{k.left} = {k.right}" for k in s.keys],
            "cardinality": s.cardinality,
            "reasons": s.reasons[:3],
            "warnings": s.warnings[:3],
        }
        for s in suggest_links(tables, {})
    ]


def _chain(
    tables: list[Table], make_id: Callable[[int], str]
) -> tuple[_Built | None, list[dict[str, str]]]:
    pool = list(tables)
    unconnected: list[dict[str, str]] = []
    steps: list[tuple[ScopeStep, BuiltLink]] = []
    counter = 0

    def run(spec: LinkSpec, s: LinkSuggestion, left: Table, right: Table) -> Table:
        nonlocal counter
        built = build_link(spec, left, right)
        counter += 1
        name = spec.name if spec.kind == "append" and spec.name else f"{left.name} + {right.name}"
        p = built.preview
        step = ScopeStep(
            spec=spec,
            left_name=left.name,
            right_name=right.name,
            kind=spec.kind,
            confidence=s.confidence,
            reasons=s.reasons[:4],
            n_left=p.n_left,
            n_right=p.n_right,
            n_result=p.n_result,
            row_multiplication=p.row_multiplication,
            warnings=[w.model_dump() for w in p.warnings],
            requires_ack=p.requires_ack,
            ack_reasons=p.ack_reasons,
            result_name=name,
        )
        steps.append((step, built))
        return Table(
            id=make_id(counter),
            name=name,
            frame=built.frame,
            columns=built.columns,
            fingerprint=built.fingerprint,
            sources=(left.id, right.id),
        )

    # 1. Appends: stack files with the same columns.
    while len(pool) > 1:
        s = _best(suggest_links(pool, {}), {"append"})
        if s is None:
            break
        by = {t.id: t for t in pool}
        left, right = by[s.left], by[s.right]
        merged = run(_spec(s), s, left, right)
        pool = [t for t in pool if t.id not in {left.id, right.id}] + [merged]
    if not pool:
        return None, unconnected
    # 2. Joins onto the most detailed table.
    base = max(pool, key=lambda t: t.frame.height)
    rest = [t for t in pool if t.id != base.id]
    progress = True
    while rest and progress:
        progress = False
        found = [
            (t, _best(suggest_links([base, t], {}), {"join", "time_aligned"}, base.id))
            for t in rest
        ]
        found = [(t, s) for t, s in found if s is not None]
        if not found:
            break
        t, s = max(found, key=lambda x: x[1].confidence)
        try:
            base = run(_orient(s, base.id), s, base, t)
        except LinkError as exc:
            unconnected.append({"table": t.name, "reason": str(exc)})
        rest = [x for x in rest if x.id != t.id]
        progress = True
    unconnected.extend(
        {
            "table": t.name,
            "reason": (
                "no column shares enough values with the other files to join on, and its "
                "columns differ too much to stack"
            ),
        }
        for t in rest
    )
    return _Built(table=base, steps=steps), unconnected


def plan_scope(tables: list[Table]) -> tuple[ScopePlan, _Built | None]:
    if not tables:
        msg = "Choose at least one table."
        raise LinkError(msg)
    built, unconnected = _chain(tables, lambda k: f"scope-{k}")
    plan = ScopePlan(
        tables=[t.name for t in tables],
        unconnected=unconnected,
        relations=_relations(tables) if len(tables) > 1 else [],
    )
    if built is not None:
        plan.steps = [s for s, _ in built.steps]
        plan.result_rows = built.table.frame.height
        plan.result_name = built.table.name
        plan.requires_ack = any(s.requires_ack for s in plan.steps)
        plan.columns = [c.model_dump(mode="json") for c in built.table.columns]
    return plan, built


def build_scope(tables: list[Table], *, acknowledged: bool) -> tuple[ScopePlan, _Built | None]:
    plan, built = plan_scope(tables)
    if plan.requires_ack and not acknowledged:
        reasons = "; ".join(r for s in plan.steps for r in s.ack_reasons)
        msg = f"Confirm that you have reviewed this: {reasons}."
        raise LinkError(msg)
    return plan, built
