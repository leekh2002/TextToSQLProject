"""Execution-result majority vote over candidates (spec 3 ⑥)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal


def result_signature(rows) -> frozenset:
    return frozenset(tuple(sorted((key, repr(value)) for key, value in row.items())) for row in rows)


@dataclass(frozen=True)
class Decision:
    kind: Literal["answer", "empty", "rejected", "none"]
    index: int | None


def decide(outcomes, total: int) -> Decision:
    if sum(1 for o in outcomes if o.rejected) * 2 > total:
        return Decision("rejected", None)
    succeeded = [o for o in outcomes if o.rows is not None]
    if not succeeded:
        return Decision("none", None)
    non_empty = [o for o in succeeded if o.rows]
    if not non_empty:
        return Decision("empty", min(o.index for o in succeeded))
    groups: dict[frozenset, list[int]] = defaultdict(list)
    for outcome in non_empty:
        groups[result_signature(outcome.rows)].append(outcome.index)
    best = min(groups.values(), key=lambda members: (-len(members), min(members)))
    return Decision("answer", min(best))
