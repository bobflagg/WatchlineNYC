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

Anya Levitov appears on **five** buildings (raw HPD), all filed from one small office at
**240 Riverside Blvd, unit CU2, Manhattan**, and all managed by **Verus Real Estate**:

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
Estate**, and the person filing them, Anya Levitov, out of 240 Riverside CU2. The owners and
apparent controllers differ building-to-building. So Levitov is almost certainly the
**managing agent / operator** for a set of buildings owned by *different* small landlords —
not the owner of any of them.

`240 Riverside Blvd CU2` is a **small shared office**, not an aggregator megaoffice and not
Levitov's alone: raw HPD shows **~8 distinct names across ~6 buildings** filing from it
(Levitov 4, Sokolov, Evdokimenko, the `1239 PUTNAM LLC`). It's a sub-degree-cap shared
address — the same class of signal as Miller's 235 River Ave.

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
```

**Pairing (the trilogy):** `case-escobar.md` = merge what WoW split (owner identity, one typo).
`case-miller.md` = un-merge what WoW conflated on a shared **address** (operational nexus).
`case-levitov.md` = un-merge on a shared **manager** (management ≠ ownership). Three cases,
one message: the owner-identity layer is precision-first, and it keeps *who owns* cleanly
separate from *who operates through this office* and *who manages the building*.
