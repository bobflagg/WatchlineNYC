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

import re
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


# --- graph read (read-only; feeds `resolve`) ----------------------------------------------------

# Map the graph's CONNECTED_BY_SPLINK method strings to the C2 contract vocabulary. `registered-llc`
# in the live graph is name-only (no DOS id+jurisdiction), so it maps to the PROBABILISTIC
# `registered-llc-name` (C2). `registered-llc-id` activates only when a DOS-entity-id join exists.
_METHOD_MAP = {
    "curated-same-owner": "curated-same-owner",
    "registered-llc": "registered-llc-name",
    "splink-fellegi-sunter": "splink-fellegi-sunter",
}

# Entity-type classification from the party name (C3 cannot-link input). Institution first, then
# corporate markers, else a natural person. Mirrors the exclusion vocabulary used elsewhere.
_INST_RE = re.compile(
    r"\b(HDFC|HOUSING DEVELOPMENT FUND|NYCHA|HOUSING AUTHORITY|CITY OF NEW YORK|DEPARTMENT|"
    r"UNIVERSITY|COLLEGE|CHURCH|HOSPITAL|MINISTR|FOUNDATION|COALITION|MUTUAL HOUSING|MHANY)\b", re.I)
_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C|CORP|INC|REALTY|ASSOCIATES?|PROPERTIES|PROPERTY|HOLDINGS?|PARTNERS|PARTNERSHIP|"
    r"VENTURES?|EQUITIES|LP|LLP|PLLC|P\.C|COMPANY|GROUP|MANAGEMENT|MGMT|TRUST|FUND|ENTERPRISES?|"
    r"GARDENS|APARTMENTS?|ESTATES?)\b", re.I)


def entity_type(name: str | None) -> str | None:
    """'institution' | 'entity' | 'person' | None (name absent). A C3 cannot-link attribute."""
    if not name or not name.strip():
        return None
    n = name.upper()
    if _INST_RE.search(n):
        return "institution"
    if _ENTITY_RE.search(n):
        return "entity"
    return "person"


def surname(name: str | None, etype: str | None) -> str | None:
    """Last whitespace token, for **persons** only (entities/institutions have no surname)."""
    if etype != "person" or not name:
        return None
    toks = name.upper().split()
    return toks[-1] if toks else None


_Q_ID_EDGES = ("MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord) WHERE a.nodeid < b.nodeid "
               "RETURN a.nodeid AS a, b.nodeid AS b, coalesce(r.method,'') AS method, "
               "coalesce(r.weight, 0) AS score")
_Q_ID_NODES = ("MATCH (a:Landlord)-[:CONNECTED_BY_SPLINK]-() "
               "RETURN DISTINCT a.nodeid AS id, a.name AS name")


def read_inputs(driver, *, database: str) -> tuple[list[dict], list[dict]]:
    """Read the identity universe from the graph as (references, edges) for `resolve` — read-only.

    References are the endpoints of `CONNECTED_BY_SPLINK` (singletons are implied, as in the legacy
    layer); `id` is the within-run `nodeid` handle (the stable `party_reference_id` is a later Phase-2
    unit). Only identity edges are read — `CONNECTED_BY_DEED` is never touched. `identifier` is `None`
    until the DOS-entity-id join exists.
    """
    with driver.session(database=database) as s:
        nodes = [{"id": r["id"], "name": r["name"]} for r in s.run(_Q_ID_NODES)]
        raw_edges = [dict(r) for r in s.run(_Q_ID_EDGES)]
    references = []
    for n in nodes:
        et = entity_type(n["name"])
        references.append({"id": n["id"], "name": n["name"], "entity_type": et,
                           "surname": surname(n["name"], et), "identifier": None})
    edges = [{"a": e["a"], "b": e["b"], "method": _METHOD_MAP.get(e["method"], e["method"]),
              "score": e["score"]} for e in raw_edges]
    return references, edges


def resolve_graph(driver, *, database: str) -> dict:
    """Read the graph and run the C3 resolver — the parallel ResolvedEntityV2 partition (read-only)."""
    references, edges = read_inputs(driver, database=database)
    return resolve(references, edges)
