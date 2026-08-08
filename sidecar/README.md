# Geosupport sidecar

A thin HTTP wrapper around NYC DCP **Geosupport Desktop Edition 25b**, so the
agent (native macOS / Python 3.13) can resolve addresses through the same
geocoder the ingestion pipeline uses. Decision **D9** in
[`specs/roadmap.md`](../specs/roadmap.md).

`python-geosupport` requires the Linux/Windows Geosupport binaries, so this image
is `linux/amd64` and runs under emulation on Apple Silicon — measured fine for
single lookups (spike-findings §8).

## Contract

The service is a **pass-through**. All interpretation (GRC classification, BBL
composition, candidate capping, geocoded-but-absent) lives in
`watchline/discovery/agent/geocode.py`, not here.

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | — | `{"release": "25b"}` |
| `POST /resolve` | `{"house_number", "street_name", "borough"}` (borough code `1`–`5`) | raw Geosupport `address()` response dict, verbatim (incl. the `.result` payload on a non-`00` GRC) |

## Build & run

Pass `--platform` explicitly (keeps it off `FROM`, avoiding the
`FromPlatformFlagConstDisallowed` lint warning):

```bash
docker build  --platform=linux/amd64 -t watchline-geosupport sidecar/
docker run -d --platform=linux/amd64 -p 8080:8080 --name geosupport watchline-geosupport
```

Then point the agent at it (already the defaults, in `.env` / `.env.example`):

```
GEOSUPPORT_URL=http://localhost:8080
GEOSUPPORT_RELEASE=25b
```

## Verify

```bash
curl -s http://localhost:8080/health
# {"release":"25b"}
```

```bash
uv run python -c "from watchline.discovery.agent.geocode import GeosupportClient; \
print(GeosupportClient().health()); \
print(GeosupportClient().resolve('115', 'BROAD STREET', '1'))"
# health reports release 25b; resolve → GeocodeOutcome.RESOLVED, bbl 1000050010
```

## Release pinning

`RELEASE`/`MAJOR`/`MINOR` in the `Dockerfile` **must** match the pipeline's
Geosupport release and `geocode.REQUIRED_RELEASE`. That shared pin is the real
coupling between agent-side and pipeline-side geocoding; a mismatch surfaces as
inexplicably missing buildings, which is why `/health` reports the release and
the client raises `GeosupportReleaseMismatch` loudly on a mismatch.
