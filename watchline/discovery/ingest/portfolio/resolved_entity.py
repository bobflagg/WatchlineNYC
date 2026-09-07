"""resolved_entity.py — the parallel `ResolvedEntityV2` identity resolver (Option B, Phase 2).

The **identity-only** owner resolution: connected components of *allowlisted identity assertions*, with the
component-consistency algorithm from the Phase-1 contracts (C2/C3). It is built **alongside** the legacy
`owner_groups.py` layer (which still unions `CONNECTED_BY_DEED` into identity) — this module never touches
that layer; the swap happens only at the Phase-5 cutover. No `CONNECTED_BY_DEED` ever enters here — that is
the invariant.

This file is the **pure core** (`resolve`): no Neo4j, no Postgres, fully hermetic. Later Phase-2 units add
the graph read (edges + per-reference attributes) and the `ResolvedEntityV2` write. See
`specs/ownership-phase1-contracts.md` (C2, C3) and `specs/ownership-migration-plan.md` (Phase 2).

Algorithm (C3): constrained clustering — hard *cannot-link* constraints + soft *should-link* edges —
realized as **constrained union-find over a canonical edge order** (deterministic; a global optimizer is
unnecessary at this scale). Because deterministic methods sort strictly before probabilistic ones, a
probabilistic merge can never pre-empt a deterministic edge, so a blocked *deterministic* edge always
reflects a genuine deterministic/attribute contradiction — routed to adjudication, never silently dropped.
"""
from __future__ import annotations

from collections import defaultdict

# C2 allowlist + C3 precedence. Deterministic methods sort strictly above probabilistic ones.
PRECEDENCE: dict[str, float] = {
    "curated-same-owner": 3.0,     # human-verified          (deterministic)
    "registered-llc-id": 2.5,      # legal id + jurisdiction (deterministic)
    "registered-llc-name": 1.5,    # normalized-name match   (probabilistic; today's registered-llc)
    "splink-fellegi-sunter": 1.0,  # probabilistic same-reference
}
DETERMINISTIC: frozenset[str] = frozenset({"curated-same-owner", "registered-llc-id"})

# Hard cannot-link attributes (C3): two references may not share a component if any of these is
# known-and-different. Within a valid component each is therefore single-valued (or unknown/None).
_HARD_ATTRS = ("entity_type", "surname", "identifier")


def _canonical_key(e: dict):
    """Total order making the partition independent of input edge order: precedence desc, score desc,
    then the unordered endpoint pair. (Sorting to this order is what gives permutation invariance.)"""
    a, b = e["a"], e["b"]
    lo, hi = (a, b) if a <= b else (b, a)
    return (-PRECEDENCE[e["method"]], -float(e.get("score", 0.0)), lo, hi)


def _compatible(sa: dict, sb: dict) -> tuple[bool, str | None]:
    """Two component summaries may merge iff no hard attribute is known-and-different."""
    for k in _HARD_ATTRS:
        va, vb = sa[k], sb[k]
        if va is not None and vb is not None and va != vb:
            return False, k
    return True, None


def resolve(references: list[dict], edges: list[dict]) -> dict:
    """Resolve identity components from allowlisted identity edges under C3 constraints.

    ``references``: the universe — ``[{"id", "entity_type"?, "surname"?, "identifier"?}, ...]``. Every
    reference is placed (singletons included). ``edges``: ``[{"a","b","method","score"?}, ...]`` — identity
    assertions only. A non-allowlisted ``method`` (e.g. any ``acris-deed*``) raises — the invariant that
    no substantive relationship enters resolution, enforced fail-closed.

    Returns ``{partition, adjudication, dropped, deterministic_core}``:
    - ``partition``   — ``{reference_id: resolution_id}`` (id keyed on the min member, deterministic);
    - ``adjudication``— deterministic edges blocked by a hard constraint (genuine contradictions to review);
    - ``dropped``     — probabilistic edges blocked by a hard constraint (dropped with provenance);
    - ``deterministic_core`` — ``{resolution_id: bool}``: did the component form via ≥1 deterministic edge
      (⇒ eligible for a durable ``entity_id`` under C1)?
    """
    for e in edges:
        if e["method"] not in PRECEDENCE:
            raise ValueError(
                f"method {e['method']!r} is not an allowlisted identity mechanism — no substantive "
                f"relationship may participate in entity resolution (C2)")

    attr = {r["id"]: {k: r.get(k) for k in _HARD_ATTRS} for r in references}
    for e in edges:
        for x in (e["a"], e["b"]):
            if x not in attr:
                raise ValueError(f"edge endpoint {x!r} is not among references")

    parent = {i: i for i in attr}
    summary = {i: dict(attr[i]) for i in attr}     # per-root, single-valued-or-None invariant
    has_det = {i: False for i in attr}             # per-root: absorbed a deterministic edge?

    def find(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    adjudication: list[dict] = []
    dropped: list[dict] = []
    for e in sorted(edges, key=_canonical_key):
        ra, rb = find(e["a"]), find(e["b"])
        if ra == rb:
            continue
        ok, conflict = _compatible(summary[ra], summary[rb])
        if ok:
            lo, hi = (ra, rb) if ra <= rb else (rb, ra)   # root = min id ⇒ stable resolution_id
            parent[hi] = lo
            summary[lo] = {k: (summary[ra][k] if summary[ra][k] is not None else summary[rb][k])
                           for k in _HARD_ATTRS}
            has_det[lo] = has_det[ra] or has_det[rb] or (e["method"] in DETERMINISTIC)
        else:
            rec = {"a": e["a"], "b": e["b"], "method": e["method"], "conflict": conflict}
            (adjudication if e["method"] in DETERMINISTIC else dropped).append(rec)

    comp: dict = defaultdict(list)
    for i in attr:
        comp[find(i)].append(i)
    partition: dict = {}
    deterministic_core: dict = {}
    for root, members in comp.items():
        rid = f"RE-{min(members)}"
        deterministic_core[rid] = has_det[root]
        for m in members:
            partition[m] = rid
    return {"partition": partition, "adjudication": adjudication,
            "dropped": dropped, "deterministic_core": deterministic_core}
