# Actor Key Namespace Registry

**Principle:** Actor identity is intentionally different between the discovery
and evidentiary graphs (Reconciliation Principle 3). Keys are namespaced so no
two regimes can collide — even if both graphs are queried in the same session.

---

## Discovery KG (`discovery` database)

| Namespace | Key scheme | Source | Node labels |
|-----------|-----------|--------|-------------|
| `ACT-LL-` | `ACT-LL-{nodeid}` | WoW `landlords_with_connections.nodeid` (integer) | `Actor:WatchlineNode:LandlordActor` |
| `ACT-ACRIS-` | `ACT-ACRIS-{sha1}` | SHA-1 of `(normalized_name, address1, address2, city, state, zip)` | `Actor:WatchlineNode` |

**Notes:**
- `LandlordActor` is a secondary label on HPD-registration-derived actors only.
  GDS portfolio projection uses `LandlordActor` to exclude ACRIS actors, which
  have no `CONNECTED_BY_*` edges and would flood WCC with singletons.
- The `nodeid` integer is stable within a given WoW snapshot but may change
  across WoW database rebuilds. The discovery graph must be fully rebuilt when
  WoW is refreshed; there is no in-place migration path.

---

## Evidentiary KG (`evidentiary` database)

| Namespace | Key scheme | Source | Node labels |
|-----------|-----------|--------|-------------|
| `ACT-` | `ACT-{uuid4}` | Random UUID4, assigned at portfolio detection time | `Actor:WatchlineNode` (OwnershipNetwork) |
| `MGT-` | `MGT-{uuid5}` | UUID5 derived from `(normalized_name, normalized_address)` | `Actor:WatchlineNode` (ManagingAgent) |

**Notes:**
- `ACT-{uuid4}` OwnershipNetwork actors are matched across pipeline re-runs via
  Jaccard similarity on their BBL sets, not by key. A given real-world portfolio
  may have a different `canonical_id` after each rebuild if the BBL set changes.
- `MGT-{uuid5}` ManagingAgent IDs are stable across re-runs for the same
  (name, address) pair. `uuid.uuid5(uuid.NAMESPACE_DNS, key)` is the derivation.

---

## Cross-graph join boundary

The two graphs share `Building.bbl` and `Event.event_id` as the conformed
vocabulary (Reconciliation Principle 2). Actor keys are **never** shared across
graphs — a discovery `ACT-LL-*` key will never appear in the evidentiary graph,
and an evidentiary `ACT-{uuid4}` will never appear in the discovery graph.

Cross-graph actor resolution (matching a discovery LandlordActor to its
evidentiary OwnershipNetwork counterpart) happens at query time by joining on
the BBL sets, not on actor keys. This is intentional — the two graphs represent
different stages of identity resolution (raw vs resolved).

---

## ADR reference

ADR-006 (Actor key prefix collision) — decided and implemented 2026-07-09.
See `docs/decisions/ADR-000-skeleton.md`.
