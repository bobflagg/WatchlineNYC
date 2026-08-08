# Deploying the POC (full graph)

A self-contained stack so stakeholders can experiment: **Neo4j** (Enterprise, eval
license — required for the source's block store format; seeded once from a dump),
the **Geosupport** sidecar, the **Streamlit** app,
and **Caddy** (HTTPS + one shared basic-auth login) — one `docker compose up` on
one VM.

```
caddy ──▶ streamlit ──▶ neo4j (seeded from Drive on first boot)
                    └──▶ geosupport
```

Only Caddy is exposed (ports 80/443). The rest talk over the internal network.

---

## 1. Make the dump and put it on Google Drive

On the source Neo4j, dump the discovery database. From the repo root:

```bash
make dump                                              # → dumps/discovery.dump
# containerized source? point the wrapper at it:
make dump NEO4J_ADMIN='docker exec <neo4j-container> neo4j-admin' DUMP_DIR=/path/mounted/into/container
```

`make dump` wraps `neo4j-admin database dump` — an **on-host, offline** operation, so
the database must be **stopped** first (Enterprise: `STOP DATABASE discovery` via
cypher-shell, dump, `START DATABASE discovery`; Community: stop the DBMS). **Aura**
has no `neo4j-admin` — use the Aura console's export/snapshot to get the `.dump`.

**Neo4j Desktop** keeps `neo4j-admin` inside each DBMS install, not on PATH. Stop
the DBMS, then either point the target at it —
`make dump NEO4J_ADMIN="/path/to/dbms/bin/neo4j-admin"` (find it via the DBMS's
"…" → Open folder → DBMS) — or use the DBMS's "…" → Open Terminal and run
`neo4j-admin database dump discovery --to-path=... --overwrite-destination=true`
directly. Any resulting `.dump` works; the seed loads it as the default DB.

Upload that file to Google Drive, share it **"Anyone with the link → Viewer"**, and
copy its **file id** from the share URL (`.../file/d/<FILE_ID>/view`). The file may
be named anything — the container saves it as `neo4j.dump` and loads it as the
default `neo4j` database (always known to the DBMS, so no `CREATE DATABASE` step;
that's why the app runs with `NEO4J_DISCOVERY_DATABASE=neo4j`).

> **Edition:** the image is Neo4j **Enterprise** (`5.26-enterprise`), accepting the
> **evaluation license** (`NEO4J_ACCEPT_LICENSE_AGREEMENT=eval`, dev/test/POC).
> Enterprise is required because the source graph uses the Enterprise-only *block*
> store format — Community fails to load it. Set the license to `yes` if you hold a
> commercial license.
>
> **Version match:** the container's Neo4j must be the **same version or newer**
> than the dump — a dump from a newer Neo4j won't load ("newer version than the
> current binaries; downgrade is not supported"). The image is pinned to
> `2026.04.0-enterprise` in `neo4j/Dockerfile`; find your source's version with
> `CALL dbms.components()` (or the Neo4j Desktop DBMS version) and set the tag to
> match.

## 2. Pick a VM

Full graph = ~76M relationships, tens of GB on disk. Size for it:

- **RAM: ~32GB** (defaults: heap 8g + pagecache 12g; tune `NEO4J_HEAP` / `NEO4J_PAGECACHE`). You can run smaller and slower on SSD.
- **Disk: 100GB+ SSD** — room for the dump + the expanded store (~2× during load) + headroom. On GCP use a persistent disk; the `neo4j-data` volume lives there.
- Keep the dump **on Google Drive / same-cloud** so the pull is fast; on GCP a GCE VM is the natural host.

**Cost tip:** a 32GB VM is ~$150–250/mo on demand — **stop it between demos** to cut that sharply (the seeded volume persists, so it comes back instantly).

## 3. Configure and launch

```bash
cd deploy
cp .env.example .env
$EDITOR .env          # fill in the values below
docker run --rm caddy caddy hash-password --plaintext 'pick-a-password'   # → BASIC_AUTH_HASH
docker compose up -d --build
docker compose logs -f neo4j        # watch the one-time seed (download + load)
```

Required in `.env`: `ANTHROPIC_API_KEY`, `NEO4J_PASSWORD`, `DISCOVERY_GDRIVE_ID`,
`BASIC_AUTH_USER`, `BASIC_AUTH_HASH`. For HTTPS set `SITE_ADDRESS` to a domain
pointed at the VM (Caddy gets a cert automatically); for an IP-only POC leave
`SITE_ADDRESS=:80`. `TAVILY_API_KEY` enables web search in deep investigations;
`WATCHLINE_MODEL` can pin a cheaper model.

**First boot is slow** — it downloads the multi-GB dump and loads it offline before
Neo4j serves (10–20+ min; the healthcheck's `start_period` is 30m). Every boot
after is instant: the `neo4j-data` volume carries a `.watchline-seeded` sentinel,
so the dump is pulled from Drive exactly once (Drive throttles repeated large-file
downloads — this avoids it). To force a re-seed, `docker volume rm` the
`deploy_neo4j-data` volume.

## 4. Before you share the URL

- **Cap Anthropic spend** in the Anthropic console (workspace/key budget). Deep
  investigations are the priciest tier; the in-app cost caption shows per-query
  cost, but a hard cap is the safety net.
- Access is gated by Caddy basic-auth. Share the URL + the one login.
- The sidebar **trust toggle** unlocks Tier-4 deep investigations — leave it
  available for the demo (that's the headline capability), paired with the spend cap.

## Deploy to a cloud VM — DigitalOcean

The stack is a single-host Docker Compose app, so it runs on any Linux VM you get
root on. On DigitalOcean that means a **Droplet** — **not** App Platform.

> **Droplet, not a container platform.** DO **App Platform** (and the equivalent
> serverless-container tiers elsewhere — Cloud Run, Fargate/App Runner, Azure
> Container Apps, Render) are built for *stateless* services with capped memory and
> no real persistent disk. They can't host a stateful ~32GB Neo4j with a tens-of-GB
> volume and a seed-on-boot step. Rule of thumb: **a VM you get root on → yes; a
> "just give us a container" platform → no.**

1. **Create the Droplet.** Choose **Memory-Optimized** or **General Purpose**, sized
   per [§2](#2-pick-a-vm) — **≥ 32GB RAM**, **100GB+ disk** (the Droplet's SSD, or
   attach a Volume and put the `neo4j-data` volume on it). Use the **Docker**
   Marketplace image (Docker + Compose preinstalled) or install Docker yourself. All
   DO Droplets are **x86/amd64**, which is what Geosupport needs — no arch worries.
2. **Open the firewall** for inbound **22, 80, 443** (DO Cloud Firewall or `ufw`).
3. **Deploy.** SSH in, then follow the numbered steps above:
   `git clone` the repo → make the dump and put it on Drive ([§1](#1-make-the-dump-and-put-it-on-google-drive))
   → `cd deploy`, fill `.env`, `docker compose up -d --build` ([§3](#3-configure-and-launch)).
4. **DNS + HTTPS.** Point an **A record** at the Droplet's IP and set
   `SITE_ADDRESS=your.domain` — Caddy fetches a cert automatically. No domain? Leave
   `SITE_ADDRESS=:80` and reach it at `http://<droplet-ip>` (basic-auth still applies).
5. **Before sharing**, do [§4](#4-before-you-share-the-url) (cap Anthropic spend; hand
   out the URL + the one basic-auth login).

> **DO billing gotcha.** Unlike the "stop it between demos" tip in [§2](#2-pick-a-vm)
> (which suits GCE), a **powered-off Droplet still bills** on DigitalOcean. To
> actually stop the meter, take a **Snapshot** (cheap, per-GB) and **destroy** the
> Droplet; recreate from the snapshot for the next demo. The seeded graph rides in
> the snapshot, so you skip the first-boot re-seed.

Any other x86 VM works identically — **AWS EC2** (e.g. `r5`/`m5` sizes), **Hetzner**
(strong value), **Linode**. Just avoid **ARM** instances (AWS Graviton, GCP Tau
T2A, Azure Ampere): Geosupport's native library is amd64-only.

## Local smoke test (use your Neo4j Desktop graph)

Testing the container wiring on a Mac? Don't duplicate the graph into Docker — run
just the app + Geosupport and point them at the Neo4j you already run in **Neo4j
Desktop** (`docker-compose.local.yml`, via `host.docker.internal`). No dump, no
seeding, no big Docker VM.

```bash
# In deploy/.env set NEO4J_PASSWORD to your Desktop password (and keep
# NEO4J_DISCOVERY_DATABASE=discovery). Make sure Neo4j Desktop is RUNNING.
cd deploy && docker compose -f docker-compose.local.yml up --build
open http://localhost:8501            # no Caddy/auth locally
```

If Streamlit can't reach Neo4j: confirm Desktop is started and its Bolt connector
listens on `7687`; on some setups you must set Desktop's
`server.bolt.listen_address=0.0.0.0:7687` so `host.docker.internal` can reach it.

### Full stack locally (Neo4j in Docker, seeded from a local dump)

To exercise the actual deploy artifact — Neo4j *in a container* — on a Mac without
the Google Drive round-trip, seed from a **local dump** via
`docker-compose.seed-local.yml`:

1. Build the dump: `make dump` (step 1 above) → `dumps/discovery.dump`.
2. Docker Desktop → Settings → Resources: raise **Memory** (≥ `NEO4J_HEAP` +
   `NEO4J_PAGECACHE` + ~4GB) and the **Virtual disk limit** — the dump + expanded
   store live in Docker's disk image, so budget ~2× the store (e.g. 120GB+).
3. In `deploy/.env`, set laptop-friendly memory, e.g. `NEO4J_HEAP=2g` and
   `NEO4J_PAGECACHE=4g` (the graph runs with less page cache, just slower).
4. Launch, seeding from the local dump (the app is published on :8501 directly, so
   you can skip Caddy/auth locally):
   ```bash
   cd deploy
   DISCOVERY_DUMP="$PWD/../dumps/discovery.dump" \
     docker compose -f docker-compose.yml -f docker-compose.seed-local.yml up -d --build
   docker compose logs -f neo4j      # watch the one-time offline load
   open http://localhost:8501
   ```

The load runs once onto the `neo4j-data` volume; `docker compose down` keeps it
(the sentinel makes the next start instant). To re-seed, `docker volume rm
deploy_neo4j-data`. This is the same `docker-compose.yml` the VM uses — the overlay
only swaps the dump source (local file vs Drive) and exposes the app port.

## Notes / troubleshooting

- **`.env` is secret — never commit it** (it's gitignored).
- **Re-seed / update the graph:** replace the Drive file (or set a new
  `DISCOVERY_GDRIVE_ID`), `docker volume rm deploy_neo4j-data`, `up -d` again.
- **Seed download fails / neo4j crash-loops:** `DISCOVERY_GDRIVE_ID` must be the file
  id or a full share URL, and the file must be shared **"Anyone with the link →
  Viewer"** (gdown can't fetch a private file). After fixing it, `docker compose
  down` then `make deploy-up` (the seed sentinel is only set on success, so it
  re-seeds cleanly).
- **`variable is not set, defaulting to blank string`:** a value in `.env` has a
  literal `$` (usually the bcrypt `BASIC_AUTH_HASH`). Double each `$` → `$$`.
- **gdown quota / interstitial:** if the download fails with a quota message, wait
  and retry (Drive throttles big public files); the image pins a recent gdown.
- **`Block format detected ... unavailable in this edition`:** the source graph
  uses Neo4j's Enterprise-only block store format, so the container runs Neo4j
  Enterprise (eval license). If you re-add a Community image, the load fails here.
  After switching editions, wipe the half-loaded volume: `docker volume rm
  deploy_neo4j-data`, then relaunch.
- **Laptop testing:** the full graph needs the VM. To smoke-test the *wiring*
  locally, use a small dump and drop `NEO4J_HEAP`/`NEO4J_PAGECACHE` to ~`1g` (the
  32GB defaults will exceed Docker Desktop's VM).
- **Geosupport** is x86-only; the compose builds it `linux/amd64` (native on a
  GCE VM). Address-lookup samples need it; the landlord/deep-investigation demos
  don't.
- **Single instance only:** conversation state is per-process (`InMemorySaver`);
  don't scale `streamlit` to multiple replicas.
