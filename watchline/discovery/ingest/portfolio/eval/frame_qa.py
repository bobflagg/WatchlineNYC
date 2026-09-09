"""eval/frame_qa.py — LEAD-FACING triage over the cutover frame (NOT for the blinded reviewer).

Reads `cutover_key.jsonl` (which carries v2's decision + the legacy owner_group / v2 resolution_id) plus
`review_queue.jsonl` (the A/B anchor names), joins them, consults the graph for the connecting mechanism and
blob shape, and classifies every pair so the project lead knows **where to spend judgment** and **what to
personally trace** before the frame is scored.

**Blinding boundary — do NOT feed this into owner-review.** Its output is derived from v2's own decision
(`v2_decision`, the split/merge structure), so consulting it while adjudicating would make the gate circular
(validating v2 against v2). It lives on the WatchlineNYC side, reads the private key, and emits to
`eval_out/cutover/frame_qa.jsonl` — a QA artifact, never imported into the blinded tool.

Buckets, by descending priority:
  * **RED_FLAG_MERGE / RED_FLAG_SPLIT** — v2 did something the invariant says it shouldn't: merged
    dissimilar-surname nodes, held a merged entity together with a *non-identity* edge, or split two nodes
    that a *direct identity* edge connects. Trace these by hand.
  * **name_similar_split** — S1 split of same/typo-surname nodes: a possible real same-owner v2 wrongly split
    (the F4 `registered-llc-id` recall misses, or a typo/HDFC that should be SAME). Needs careful review.
  * **same_llc_split** — S1 split whose two entities share a `registered-llc` edge across the A/B boundary AND
    a *private* (non-financier) DOF owner of record: dissimilar-surnamed co-principals of the SAME owning LLC
    (CUT-0029), a likely SAME false-split the surname heuristic would otherwise bury in routine_blob_split.
    Needs review. Three things demote a cross-boundary edge back to routine: (a) a *transitive* path through a
    third entity — the OG-110 blob — which has no direct cross-boundary edge; (b) the only shared owner being a
    DOF placeholder or a financier / government / LIHTC-investor vehicle (City, NYC HDC, NY Equity Fund), tagged
    `same-llc-noise` — the F5 discount + placeholder drop (a shared HDFC is a real owner and stays); (c) a
    SINGLE small owner LLC (<=JV_DEGREE_MAX buildings citywide) with NO shared office — a two-party JV / single
    co-owned asset (common control, not identity), tagged `same-llc-jv-no-office`. A shared office, >1 shared
    LLC, a large/dominant owner, a person-owner, or an EPONYMOUS owner (the LLC carries an anchor's own
    surname — that person's entity, tagged `eponymous-owner`) keeps it promoted.
  * **routine_blob_split** — S1 split of dissimilar-surname nodes connected only via relationship edges
    (registered-llc/deed), often transitive through a bridge: the OG-110/OG-1073 pattern, expected DIFFERENT.
  * **routine_merge** — S2 retained merge, surname-consistent, held by an identity method: expected SAME.
"""
from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher

_IDENTITY_METHODS = frozenset({"splink-fellegi-sunter", "curated-same-owner"})
_TYPO_RATIO = 0.85     # normalized-surname similarity at/above this (but not equal) reads as a typo variant
# S2 false-merge candidates: a NON-curated retained merge with many members. Member count is the FM surface
# (each extra member is another merge decision that could be wrong). NB common-surname is NOT a useful
# discriminator in this population — the median surname frequency is ~268, so nearly every merge is
# common-surnamed; only member count separates the risky merges. `surname_freq` is kept as context.
COMMON_SURNAME_MIN = 50    # freq at/above this = "common surname" — reported as context, not a flag
LARGE_MERGE_MIN = 5        # v2-entity member count at/above this -> a larger (higher-FM-surface) merge


# A shared registered owner that is a FINANCIER / government / pass-through vehicle, not the private
# beneficial owner — co-occurrence noise that must NOT read as a same-owner partner-split (mirrors the F5
# discount / fingerprint._FINANCIER_CATEGORIES). NB **HDFC** ("HOUSING DEVELOPMENT FUND") is deliberately
# NOT here — a shared HDFC is a genuine nonprofit owner (CUT-0001), kept for review; only City-finance,
# agency, and LIHTC-investor vehicles are dropped. Substrings are unambiguous-government only (no bare
# "NEW YORK CITY", which a private "…NY CITY REALTY LLC" would trip); the HDC pattern is "DEVELOPMENT CORP",
# which does not match HDFC's "DEVELOPMENT FUND CORP".
_FINANCIER_OWNER = (
    "HOUSING DEVELOPMENT CORP", "HOUSING DEV CORP",     # NYC HDC (city finance agency)
    "NYCHA", "HOUSING AUTHORITY",
    "CITY OF NEW YORK", "COMMISSIONER OF FINANCE",
    "STATE OF NEW YORK", "DORMITORY AUTHORITY", "DEPARTMENT OF",
    "EQUITY FUND",                                      # LIHTC syndicator / passive investor vehicle
)


def _financier(owner: str) -> bool:
    """True if a shared registered-owner name is a financier/government/pass-through (co-occurrence noise)."""
    u = (owner or "").upper()
    return any(p in u for p in _FINANCIER_OWNER)


# DOF placeholder / non-owner strings that carry no beneficial owner — must not read as a shared owner.
_PLACEHOLDER_OWNER = ("UNAVAILABLE", "UNKNOWN", "NO OWNER", "OWNER UNKNOWN", "SEE ", "N/A")


def _placeholder(owner: str) -> bool:
    """True if `owner` is a DOF placeholder (blank / 'UNAVAILABLE OWNER' / etc.), not a real entity."""
    u = (owner or "").strip().upper()
    return not u or any(p in u for p in _PLACEHOLDER_OWNER)


# A single shared owner LLC on no more than this many buildings citywide, with NO shared office, is a
# two-party JV / single co-owned asset (association, not identity) — not a fragmented one-operation split.
JV_DEGREE_MAX = 4


def _eponymous(owner: str, *names: str) -> bool:
    """True if the owner LLC name carries an anchor's surname as a whole token (>=4 chars): the LLC is that
    person's OWN named entity (e.g. anchor 'Josephine Parlanti' + owner 'PARLANTI GROUP LLC'), so a
    cross-node building in it is an identity link, not a stranger JV — it should not be demoted as one."""
    toks = {t for t in "".join(c if c.isalnum() else " " for c in (owner or "").upper()).split() if len(t) >= 4}
    return any(_surname(n) in toks for n in names if len(_surname(n)) >= 4)


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _surname(name: str) -> str:
    toks = (name or "").strip().split()
    return _norm(toks[-1]) if toks else ""


def surname_relation(a_name: str, b_name: str) -> str:
    """'same' | 'typo' | 'different' — the identity-relevant relation between two anchor names' surnames."""
    sa, sb = _surname(a_name), _surname(b_name)
    if not sa or not sb:
        return "different"
    if sa == sb:
        return "same"
    return "typo" if SequenceMatcher(None, sa, sb).ratio() >= _TYPO_RATIO else "different"


def name_ratio(a_name: str, b_name: str) -> float:
    return round(SequenceMatcher(None, _norm(a_name), _norm(b_name)).ratio(), 3)


def classify(f: dict) -> dict:
    """Pure: bucket + priority (3=highest) + flags from a pair's assembled facts. `f` keys:
    stratum, surname_relation; S1: path_methods (list), path_hops (int); S2: entity_surname_count,
    entity_methods (list)."""
    flags: list[str] = []
    rel = f.get("surname_relation", "different")

    if f["stratum"] == "S2_retained_merge":
        methods = set(f.get("entity_methods") or [])
        # v2 entities are identity-only components by construction, and the pipeline also writes redundant
        # registered-llc CONNECTED_BY_SPLINK edges that merely CO-EXIST among members — so the presence of a
        # non-identity edge is NOT a breach. The real canary is an entity with NO identity edge at all.
        identity_present = bool(methods & _IDENTITY_METHODS)
        if (f.get("entity_member_count") or 1) > 1 and not identity_present:
            return {"bucket": "RED_FLAG_MERGE", "priority": 3,
                    "flags": ["merge-not-identity-connected:" + (",".join(sorted(methods)) or "none")]}
        curated = "curated-same-owner" in methods
        # Suspicious-but-not-a-breach: an uncurated entity spanning surnames, or dissimilar anchor names.
        if (f.get("entity_surname_count") or 1) > 1 and not curated:
            flags.append("merge-spans-surnames")
        if rel == "different":
            flags.append("merge-dissimilar-anchor-names")
        # False-MERGE candidates (symmetric to name_similar_split's false-splits): a NON-curated merge with
        # many members is where a retained merge is most likely wrong — the FM side the gate estimates.
        # Curated merges are audited, so exempt. (common-surname is context only — see LARGE_MERGE_MIN note.)
        if not curated and (f.get("entity_member_count") or 1) >= LARGE_MERGE_MIN:
            common = f" common-surname:{f.get('surname_freq')}" if f.get("common_surname") else ""
            flags.append(f"large-merge:{f.get('entity_member_count')}{common}")
        if flags:
            return {"bucket": "review_merge", "priority": 2, "flags": flags}
        return {"bucket": "routine_merge", "priority": 1, "flags": []}

    # S1_split — endpoints are two *different* v2 entities; the path lives in the legacy edge set.
    methods = set(f.get("path_methods") or [])
    has_relationship = bool(methods - _IDENTITY_METHODS)       # registered-llc / deed on the path
    if rel in ("same", "typo"):
        return {"bucket": "name_similar_split", "priority": 2, "flags": [f"split-of-{rel}-surname"]}
    if methods and not has_relationship:
        # an all-identity path between two nodes v2 put in *different* entities — shouldn't happen cleanly.
        return {"bucket": "RED_FLAG_SPLIT", "priority": 3, "flags": ["direct-identity-path-but-split"]}
    # Same-registered-LLC override (partner-split blind spot). A registered-llc edge crossing the A/B entity
    # boundary DIRECTLY means both entities own buildings registered to the SAME owning LLC — differently-named
    # co-principals of one LLC (CUT-0029: Sackman/Hefelfinger both on 212-214 Realty), a likely SAME
    # false-split. Dissimilar surnames would else route this to routine_blob_split=expected-DIFFERENT, hiding
    # it. Promote to review. Crucially this is a DIRECT cross-boundary edge, NOT the shortestPath hop count
    # (which runs between arbitrary entity reps and buries the edge one hop in) — and NOT a transitive chain
    # A-llc-X-llc-B through a THIRD entity (the OG-110 blob), which has no direct A<->B edge and stays routine.
    # See phase-2 findings F10 / eval-protocol §3.1.
    if f.get("cross_registered_llc"):
        raw = f.get("shared_llc_owners") or []
        private = [o for o in raw if not _placeholder(o) and not _financier(o)]
        if not private:
            # Every shared registered owner is a DOF placeholder ("UNAVAILABLE OWNER") or a financier /
            # government / LIHTC-investor pass-through (City, NYC HDC, NY Equity Fund) — co-occurrence noise,
            # not a private same-owner (the F5 discount + placeholder drop). A shared HDFC / private LLC is
            # neither and stays promoted.
            return {"bucket": "routine_blob_split", "priority": 0, "flags": ["same-llc-noise"]}
        degs = f.get("shared_owner_degrees") or {}
        eponymous = len(private) == 1 and _eponymous(private[0], f.get("a_name", ""), f.get("b_name", ""))
        if (len(private) == 1 and not f.get("shared_office")
                and (degs.get(private[0]) or 999) <= JV_DEGREE_MAX and not eponymous):
            # A SINGLE small owner LLC (<=JV_DEGREE_MAX buildings citywide) with NO shared office across two
            # otherwise-separate portfolios is a two-party JV / one co-owned asset — common control, not
            # identity (Option B / R3). Pervasive overlap (a shared office, >1 shared LLC, a dominant/large
            # owner, or a person-owner) keeps it promoted; an EPONYMOUS owner (the LLC carries an anchor's
            # own surname — CUT-0052 PARLANTI GROUP) is that person's entity, an identity link not a JV.
            return {"bucket": "routine_blob_split", "priority": 0, "flags": ["same-llc-jv-no-office"]}
        flags = ["same-registered-llc-direct"] + (["eponymous-owner"] if eponymous else [])
        return {"bucket": "same_llc_split", "priority": 2, "flags": flags}
    return {"bucket": "routine_blob_split", "priority": 0,
            "flags": ["transitive-bridge"] if (f.get("path_hops") or 0) >= 2 else []}


# ---- graph reads (read-only) ------------------------------------------------------------------------

_OG_STATS = """
UNWIND $gids AS gid
MATCH (og:OwnerGroup {owner_group_id: gid})<-[:IN_OWNER_GROUP]-(l:Landlord)
RETURN gid AS gid, count(l) AS size,
       count(DISTINCT toUpper(split(l.name,' ')[-1])) AS surnames
"""

_S1_PATHS = """
UNWIND $pairs AS pr
MATCH (:ResolvedEntityV2 {resolution_id: pr.a})<-[:IN_RESOLVED_ENTITY_V2]-(la:Landlord)
WITH pr, collect(DISTINCT la)[0] AS a
MATCH (:ResolvedEntityV2 {resolution_id: pr.b})<-[:IN_RESOLVED_ENTITY_V2]-(lb:Landlord)
WITH pr, a, collect(DISTINCT lb)[0] AS b
OPTIONAL MATCH p = shortestPath((a)-[:CONNECTED_BY_SPLINK|CONNECTED_BY_DEED*..10]-(b))
RETURN pr.pair_id AS pair_id,
       [r IN relationships(p) | coalesce(r.method, type(r))] AS methods,
       CASE WHEN p IS NULL THEN null ELSE length(p) END AS hops
"""

_S2_PROFILE = """
UNWIND $rids AS rid
MATCH (e:ResolvedEntityV2 {resolution_id: rid})<-[:IN_RESOLVED_ENTITY_V2]-(l:Landlord)
OPTIONAL MATCH (l)-[r:CONNECTED_BY_SPLINK]-(:Landlord)-[:IN_RESOLVED_ENTITY_V2]->(e)
RETURN rid AS rid, count(DISTINCT l) AS members,
       count(DISTINCT toUpper(split(l.name,' ')[-1])) AS surname_count,
       collect(DISTINCT toUpper(split(l.name,' ')[-1])) AS surnames,
       collect(DISTINCT r.method) AS methods
"""

# Does a registered-llc edge DIRECTLY cross the A/B entity boundary? (both entities own a building registered
# to the same owning LLC = partner-split, vs. a transitive chain through a third entity = OG-110 blob). This
# is the real same-owning-entity signal — independent of which reps shortestPath happened to pick.
_S1_CROSS_LLC = """
UNWIND $pairs AS pr
OPTIONAL MATCH (:ResolvedEntityV2 {resolution_id: pr.a})<-[:IN_RESOLVED_ENTITY_V2]-(la:Landlord)
      -[r:CONNECTED_BY_SPLINK]-(lb:Landlord)-[:IN_RESOLVED_ENTITY_V2]->(:ResolvedEntityV2 {resolution_id: pr.b})
WHERE r.method = 'registered-llc'
RETURN pr.pair_id AS pair_id, count(r) > 0 AS cross_llc
"""

# The DOF owner-of-record name(s) shared between the two entities' buildings — recovered to apply the
# financier/institutional filter (`_financier`) the edge alone can't carry (the registered-llc edge stores
# no name, and llc_edges' own exclude list misses HDC / equity funds). Shared directly (not transitively),
# so it also confirms the same-owning-entity reading. OPTIONAL so every pair returns a row.
_S1_SHARED_OWNERS = """
UNWIND $pairs AS pr
MATCH (:ResolvedEntityV2 {resolution_id: pr.a})<-[:IN_RESOLVED_ENTITY_V2]-(la:Landlord)
UNWIND la.bbls AS ab
WITH pr, collect(DISTINCT ab) AS abbls
MATCH (:ResolvedEntityV2 {resolution_id: pr.b})<-[:IN_RESOLVED_ENTITY_V2]-(lb:Landlord)
UNWIND lb.bbls AS bb
WITH pr, abbls, collect(DISTINCT bb) AS bbbls
OPTIONAL MATCH (ba:Building) WHERE ba.bbl IN abbls AND ba.dof_ownername IS NOT NULL
WITH pr, bbbls, collect(DISTINCT toUpper(ba.dof_ownername)) AS aown
OPTIONAL MATCH (bb:Building) WHERE bb.bbl IN bbbls AND bb.dof_ownername IS NOT NULL
WITH pr, aown, collect(DISTINCT toUpper(bb.dof_ownername)) AS bown
RETURN pr.pair_id AS pair_id, [x IN aown WHERE x IN bown] AS shared_owners
"""

# Do the two entities' landlords share a business address (same office)? A strong "one operation" tell that
# separates a fragmented single owner (keep as same_llc_split) from a two-party JV (a single shared LLC, no
# shared office -> demote). Exact bizaddr match is conservative (format drift misses some real shared offices,
# which then stay promoted for review — the safe direction).
_S1_SHARED_OFFICE = """
UNWIND $pairs AS pr
MATCH (:ResolvedEntityV2 {resolution_id: pr.a})<-[:IN_RESOLVED_ENTITY_V2]-(la:Landlord)
WITH pr, collect(DISTINCT toUpper(coalesce(la.bizaddr, ''))) AS aad
MATCH (:ResolvedEntityV2 {resolution_id: pr.b})<-[:IN_RESOLVED_ENTITY_V2]-(lb:Landlord)
WITH pr, aad, collect(DISTINCT toUpper(coalesce(lb.bizaddr, ''))) AS bad
RETURN pr.pair_id AS pair_id, size([x IN aad WHERE x IN bad AND x <> '']) > 0 AS shared_office
"""

# Citywide degree of an owner name (distinct buildings it is DOF owner of) — a single-purpose LLC sits low,
# a placeholder / large holder sits high. Feeds the JV-degree test.
_OWNER_DEGREE = """
UNWIND $names AS nm
OPTIONAL MATCH (g:Building) WHERE toUpper(g.dof_ownername) = nm
RETURN nm AS name, count(DISTINCT g) AS deg
"""

# Population surname frequency (distinct landlord nodes per surname) — for common-name detection.
_SURNAME_FREQ = """
MATCH (l:Landlord)
WITH toUpper(split(l.name,' ')[-1]) AS surname, count(DISTINCT l) AS n
WHERE surname <> '' RETURN surname, n
"""


def _run(driver, database, query, **params):
    with driver.session(database=database) as s:
        return [r.data() for r in s.run(query, **params)]


def read_graph_facts(driver, *, database: str, key_rows: list[dict]) -> dict:
    """Fetch per-pair graph facts keyed by pair_id (S1 path/blob) and per-entity facts (S2)."""
    s1 = [r for r in key_rows if r["stratum"] == "S1_split"]
    s2 = [r for r in key_rows if r["stratum"] == "S2_retained_merge"]
    gids = sorted({r["owner_group_id"] for r in s1 if r.get("owner_group_id")})
    og = {r["gid"]: r for r in _run(driver, database, _OG_STATS, gids=gids)} if gids else {}
    pairs = [{"pair_id": r["pair_id"], "a": r["a_rid"], "b": r["b_rid"]} for r in s1]
    paths = {r["pair_id"]: r for r in _run(driver, database, _S1_PATHS, pairs=pairs)} if pairs else {}
    xllc = {r["pair_id"]: r["cross_llc"] for r in _run(driver, database, _S1_CROSS_LLC, pairs=pairs)} if pairs else {}
    sown = {r["pair_id"]: (r["shared_owners"] or [])
            for r in _run(driver, database, _S1_SHARED_OWNERS, pairs=pairs)} if pairs else {}
    soff = {r["pair_id"]: bool(r["shared_office"])
            for r in _run(driver, database, _S1_SHARED_OFFICE, pairs=pairs)} if pairs else {}
    names = sorted({n for owners in sown.values() for n in owners})
    odeg = {r["name"]: r["deg"] for r in _run(driver, database, _OWNER_DEGREE, names=names)} if names else {}
    rids = sorted({r["resolution_id"] for r in s2 if r.get("resolution_id")})
    prof = {r["rid"]: r for r in _run(driver, database, _S2_PROFILE, rids=rids)} if rids else {}
    freq = {r["surname"]: r["n"] for r in _run(driver, database, _SURNAME_FREQ)} if s2 else {}
    return {"og": og, "paths": paths, "cross_llc": xllc, "shared_owners": sown,
            "shared_office": soff, "owner_degree": odeg, "prof": prof, "surname_freq": freq}


def assemble(key_rows: list[dict], queue_by_id: dict, graph: dict) -> list[dict]:
    """Join key + queue names + graph facts into per-pair fact dicts, then classify each."""
    out = []
    for k in key_rows:
        q = queue_by_id.get(k["pair_id"], {})
        a_name, b_name = q.get("a", {}).get("name", ""), q.get("b", {}).get("name", "")
        f = {"pair_id": k["pair_id"], "stratum": k["stratum"], "v2_decision": k.get("v2_decision"),
             "a_name": a_name, "b_name": b_name,
             "surname_relation": surname_relation(a_name, b_name), "name_ratio": name_ratio(a_name, b_name)}
        if k["stratum"] == "S1_split":
            og = graph["og"].get(k.get("owner_group_id"), {})
            path = graph["paths"].get(k["pair_id"], {})
            f.update({"owner_group_id": k.get("owner_group_id"),
                      "blob_size": og.get("size"), "blob_surnames": og.get("surnames"),
                      "path_methods": path.get("methods") or [], "path_hops": path.get("hops"),
                      "cross_registered_llc": bool(graph.get("cross_llc", {}).get(k["pair_id"])),
                      "shared_llc_owners": (so := graph.get("shared_owners", {}).get(k["pair_id"], [])),
                      "shared_office": graph.get("shared_office", {}).get(k["pair_id"], False),
                      "shared_owner_degrees": {n: graph.get("owner_degree", {}).get(n) for n in so}})
        else:
            p = graph["prof"].get(k.get("resolution_id"), {})
            freq = graph.get("surname_freq", {})
            surname_freq = max((freq.get(s, 0) for s in (p.get("surnames") or [])), default=0)
            f.update({"resolution_id": k.get("resolution_id"), "entity_member_count": p.get("members"),
                      "entity_surname_count": p.get("surname_count"),
                      "entity_methods": [m for m in (p.get("methods") or []) if m],
                      "surname_freq": surname_freq, "common_surname": surname_freq > COMMON_SURNAME_MIN})
        f.update(classify(f))
        out.append(f)
    return out


def build(driver, *, database: str, key_path: str, queue_path: str, out_path: str) -> dict:
    key_rows = [json.loads(l) for l in open(key_path) if l.strip()]
    queue_by_id = {q["pair_id"]: q for q in (json.loads(l) for l in open(queue_path) if l.strip())}
    facts = assemble(key_rows, queue_by_id, read_graph_facts(driver, database=database, key_rows=key_rows))
    facts.sort(key=lambda x: (-x["priority"], x["bucket"], x["pair_id"]))
    with open(out_path, "w") as fh:
        for f in facts:
            fh.write(json.dumps(f) + "\n")
    buckets = Counter(f["bucket"] for f in facts)
    blobs = Counter(f["owner_group_id"] for f in facts if f.get("owner_group_id"))
    return {"n_pairs": len(facts), "buckets": dict(buckets), "out_path": out_path,
            "needs_review": [f["pair_id"] for f in facts if f["priority"] >= 2],
            "multi_pair_blobs": {g: n for g, n in blobs.items() if n > 1}}


if __name__ == "__main__":
    import argparse
    from watchline.shared.connections import neo4j_driver, NEO4J_DISCOVERY_DATABASE
    ap = argparse.ArgumentParser(description="Lead-facing cutover-frame triage (NOT for the blind reviewer).")
    ap.add_argument("--dir", default="eval_out/cutover")
    args = ap.parse_args()
    drv = neo4j_driver()
    try:
        rep = build(drv, database=NEO4J_DISCOVERY_DATABASE,
                    key_path=f"{args.dir}/cutover_key.jsonl", queue_path=f"{args.dir}/review_queue.jsonl",
                    out_path=f"{args.dir}/frame_qa.jsonl")
    finally:
        drv.close()
    print(json.dumps(rep, indent=2))
