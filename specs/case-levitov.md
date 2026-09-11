# Case study — Anya Levitov (the "shared manager, not shared owner" cluster)

The third in the trilogy with [`case-escobar.md`](case-escobar.md) and
[`case-miller.md`](case-miller.md). Escobar is the merge WatchlineNYC gets right that WoW
*splits* (owner identity). Miller is the split WatchlineNYC gets right that WoW *conflates*
on a shared **address** (operational nexus ≠ ownership). Levitov is the cleanest
illustration of the **management layer**: one operator ties five buildings together, but
they are owned by *different* parties, and the owner-identity layer correctly declines to
merge them. It's the answer, in one worked example, to *"doesn't it just merge everything?"*

Reached organically by tracing a single 2-unit walk-up outward (see the trail at the
bottom). All figures from the live `wow` schema + discovery graph on **2026-09-11**.

## The headline

Anya Levitov appears on **five** buildings (raw HPD), all managed by **Verus Real Estate**
(Anya Levitov) but filed from **two** owner offices — **33 West 60th St** and **240 Riverside
Blvd CU2** — grouped by owner:

| Building | Recorded owner (deed) | Apparent controller | Manager | WatchlineNYC portfolio |
|---|---|---|---|---|
| 349 West 53 St (Manhattan) | GATES OVERSEAS NYC | **Michael Schwarz** | Verus | `PF-…-67385` |
| 418 MacDonough St (Bklyn) | SCHWARZ, MICHAEL | **Michael Schwarz** | Verus | `PF-…-67385` |
| 124 South 2 St (Bklyn) | BOLLINGEN LLC | **Oleg Evdokimenko** | Verus | `PF-…-73027` |
| 1239 Putnam Ave (Bklyn) | Brigitee Mulholland Rev. Trust | **Dmitry Sokolov** | Verus | `PF-…-11` |
| 1111 Jefferson Ave (Bklyn) | OLCER, CEM | **Dmitry Sokolov** | Verus | `PF-…-11` |

The one constant is Levitov + Verus. Everything else changes: **five recorded owners, three
apparent controllers** (Schwarz, Evdokimenko, Sokolov).

## The finding — Levitov is a *manager*, not an owner

Read the columns: the only uniform thing across the five is the **managing agent, Verus Real
Estate** (Anya Levitov). The owners and apparent controllers differ building-to-building — and the
owners even file from **different offices**. So Levitov is almost certainly the **managing agent /
operator** for a set of buildings owned by *different* small landlords — not the owner of any of them.

**Two owner offices, not one**, split the five into their portfolios: the Schwarz pair (349 W 53 /
418 MacDonough) files from **33 West 60th St**; the Sokolov pair (1239 Putnam / 1111 Jefferson) and
Evdokimenko's 124 South 2 file from **240 Riverside Blvd CU2**. `240 Riverside CU2` is a **small
shared office** (not an aggregator megaoffice): raw HPD shows **~8 distinct names across ~6 buildings**
filing from it — a sub-degree-cap shared address, the same class of signal as Miller's 235 River Ave.
Verus/Levitov is listed as the agent at **both** addresses — which is exactly why brand-normalized
`MANAGED_BY` unifies all five while the address-based portfolios keep them apart.

## What WatchlineNYC does — and why it's right

- **No owner group.** All five buildings have `owner_group = None` — no
  `CONNECTED_BY_SPLINK`/`_DEED` edge unifies them. The precision-first owner-identity layer
  **abstains**.
- **Grouped by apparent OWNER, not by the shared manager.** The five split into **three**
  portfolios — the Schwarz pair (`67385`), the Sokolov pair (`11`), the Evdokimenko single
  (`73027`) — each around its own likely owner.
- **Levitov / Verus appear only in the management layer** (`MANAGED_BY`), never as an owner.

This is the ownership-vs-management distinction working end to end: the shared thread is a
**management operation** (one agent, one office), and the graph refuses to let "same manager /
same office" masquerade as "same owner." It's the Miller lesson (shared *address* ≠ common
owner) one level deeper — shared *agent* ≠ common owner.

## Anatomy of one `APPARENT_CONTROL` edge (why 1239 Putnam → Dmitry Sokolov)

Tracing a single edge shows how soft `APPARENT_CONTROL` is — here it's a **portfolio-anchor
artifact**, not a direct finding about the building. 1239 Putnam Ave = `bbl 3033680047`,
recorded owner (DOF) = THE BRIGITEE MULHOLLAND REVOCABLE TRUST.

1. **Sourced fact (HPD registration `814025`, expired 2021-09-01, all @ 240 Riverside Blvd CU2):**
   CorporateOwner + HeadOfficer = **1239 PUTNAM LLC** (the HeadOfficer slot holds the LLC name,
   not a person); **Officer = DMITRY SOKOLOV** (the only natural person in an owner role);
   Agent + SiteManager = **Anya Levitov / Verus**. So "Sokolov, Officer of 1239 Putnam" is
   directly sourced; everything below is inference on top.
2. **Two Landlord nodes.** Sokolov = `ACT-LL-29277`, but his `bbls` anchor is **1111 Jefferson
   Ave** (`3033810056`) — a *different* building where he is also an Officer **and**
   `REGISTERED_FOR`. 1239 Putnam is its own node, `1239 PUTNAM LLC` (`ACT-LL-14`). At 1239 Putnam
   itself Sokolov has **no** `REGISTERED_FOR` edge — this is one of the ~18.5% of
   `APPARENT_CONTROL` edges with no registration mirror.
3. **Address-only glue → one Portfolio.** The only edge joining the two nodes is
   `DMITRY SOKOLOV ──CONNECTED_BY_ADDRESS (w=2.0)── 1239 PUTNAM LLC` (both file from 240 Riverside
   CU2). No `CONNECTED_BY_SPLINK`, no deed. WCC+Louvain groups them into Portfolio `PF-…-11`
   (2 bldgs: 1111 Jefferson + 1239 Putnam).
4. **The anchor heuristic** (`pipeline.py:506–526`) picks **one anchor per portfolio — the member
   with the most BBLs — and stamps `APPARENT_CONTROL` from it onto *every* building in the
   portfolio.** Both members have exactly 1 BBL → a **tie**, broken arbitrarily (internal node
   order, *not* role). It landed on Sokolov, so he is stamped controller of both buildings,
   1239 Putnam included — though his own registration is at 1111 Jefferson.

**Why this sharpens the case.** The owner-identity layer **abstained** (`owner_group = None`):
`CONNECTED_BY_ADDRESS` is an operational-nexus signal, not an identity edge (`OwnerGroup` reads
`SPLINK`/`DEED` only), so Watchline asserts "apparent controller: Sokolov (inferred)" but never
"Sokolov owns this." Two honest heuristic weaknesses it exposes: (a) the anchor is *most-BBLs*,
**not role-based** (the code comment says so) — the tie here luckily resolved to the human over
the shell, but could have named `1239 PUTNAM LLC` instead; (b) the recall-biased Portfolio layer
keeps the shared-office address glue, so control propagated across a co-located manager's office —
exactly the over-reach the `OwnerGroup` layer is built to avoid, and did. Textbook reason
`APPARENT_CONTROL` is Type II ("a lead, not a legal determination").

## The teaching arc (why this example is strong)

The cleanest rebuttal to *"your system just merges everything into big landlords."* Here the
tool does the opposite of over-merging: handed a cluster of five buildings that share an
office and a manager, it **un-tangles them into their actual, separate owners** and keeps the
shared operator in the management layer where it belongs. If it had merged them, it would
almost certainly have been wrong — the deeds name five unrelated-looking parties.

## Caveats — leads, not verdicts

- Levitov reading as a **manager** is an inference from the pattern (constant across five
  buildings, no controller/owner assignment, shared with Verus). She *could* be a principal
  in a small investor group; the deeds would confirm. A lead to verify, not a determination.
- Apparent controller / owner-group membership are Type II inferences; recorded owner and the
  `MANAGED_BY` agent are directly sourced (HPD).

## Reproduce

Read-only. Vintage 2026-09-11.

```python
# 1) Levitov's buildings (raw HPD, any role/address)
#    SELECT DISTINCT r.bbl FROM hpd_contacts c JOIN hpd_registrations r USING(registrationid)
#    WHERE upper(btrim(c.firstname||' '||c.lastname)) = 'ANYA LEVITOV';   -> 5 bbls

# 2) Per building: recorded owner / apparent controller / manager / portfolio / owner-group
#    MATCH (b:Building {bbl:$x})
#    OPTIONAL MATCH (ac:Landlord)-[:APPARENT_CONTROL]->(b)
#    OPTIONAL MATCH (b)-[:MANAGED_BY]->(m:Manager)
#    OPTIONAL MATCH (b)-[:IN_PORTFOLIO]->(p:Portfolio)
#    OPTIONAL MATCH (ac)-[:IN_OWNER_GROUP]->(og:OwnerGroup)
#    RETURN b.address, b.dof_ownername, ac.name, m.name, p.portfolio_id, og.owner_group_id
#    -> 5 recorded owners, 3 apparent controllers, Verus on all five, og NULL on all five,
#       3 distinct portfolios.

# 3) Is 240 Riverside CU2 a shared-agent office? (raw HPD)
#    WHERE businesshousenumber='240' AND businessstreetname LIKE 'RIVERSIDE%'
#    -> ~8 distinct owner/officer names over ~6 buildings (Levitov 4, Sokolov, Evdokimenko,
#       1239 PUTNAM LLC). Small shared office; below the degree-25 aggregator cap.

# 4) Anatomy of the 1239 Putnam -> Sokolov APPARENT_CONTROL edge
#  a) raw registration roles (sourced): Sokolov = Officer; 1239 PUTNAM LLC = CorporateOwner/
#     HeadOfficer; Levitov/Verus = Agent/SiteManager. (Postgres hpd_contacts JOIN registrations
#     WHERE r.bbl='3033680047')
#  b) MATCH (l:Landlord)-[r:APPARENT_CONTROL]->(:Building {bbl:'3033680047'})
#     RETURN l.name, l.actor_id, l.bbls, r.heuristic   -> DMITRY SOKOLOV / ACT-LL-29277 /
#     ['3033810056' = 1111 Jefferson] / true   (his bbls anchor is a DIFFERENT building)
#  c) the only edge tying him to the shell that owns 1239 Putnam:
#     MATCH (:Actor{actor_id:'ACT-LL-29277'})-[r]-(:Actor{actor_id:'ACT-LL-14'}) RETURN type(r),r
#     -> CONNECTED_BY_ADDRESS {weight:2.0}   (240 Riverside CU2; no SPLINK/DEED -> og=None)
#  d) anchor rule: pipeline.py:506-526 -- most-BBLs member of the portfolio is stamped
#     APPARENT_CONTROL over ALL its buildings; here a 1-vs-1 BBL tie broke arbitrarily to Sokolov.
```

**Pairing (the trilogy):** `case-escobar.md` = merge what WoW split (owner identity, one typo).
`case-miller.md` = un-merge what WoW conflated on a shared **address** (operational nexus).
`case-levitov.md` = un-merge on a shared **manager** (management ≠ ownership). Three cases,
one message: the owner-identity layer is precision-first, and it keeps *who owns* cleanly
separate from *who operates through this office* and *who manages the building*.
