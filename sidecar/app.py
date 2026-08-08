"""Geosupport sidecar — a thin pass-through HTTP service (decision D9, P2-1).

Two endpoints, matching the contract ``watchline.discovery.agent.geocode``'s
client already targets:

* ``GET  /health``  → ``{"release": "<25b>"}``. Drives
  :meth:`GeosupportClient.health`, which fails loudly if the release does not
  match the pipeline's.
* ``POST /resolve`` ``{house_number, street_name, borough}`` → the **raw**
  ``python-geosupport`` ``address()`` response dict, verbatim.

**All interpretation stays out of this container.** GRC classification, BBL
composition, candidate capping, and the geocoded-but-absent distinction live in
``geocode.py`` — in version control and unit-tested — not here (spike-findings
§7). This service does exactly two things: report the pinned release, and hand
Geosupport's response back untouched.

python-geosupport raises :class:`GeosupportError` on any non-``'00'`` GRC. That
exception carries the full response on ``.result`` (GRC, Reason Code, Message,
and ``List of Street Names`` for the disambiguation path), so both the success
and failure paths return the same shape — which is precisely what
``interpret()`` consumes.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request
from geosupport import Geosupport, GeosupportError
from waitress import serve

#: The pinned release, single-sourced from the environment the Dockerfile sets.
#: Reported by /health and checked against ``geocode.REQUIRED_RELEASE`` on the
#: client side; a mismatch is raised loudly, never warned about.
RELEASE = os.environ.get("RELEASE", "25b")

app = Flask(__name__)

# Instantiate once at import. If the Geosupport files or shared libraries are
# missing, this raises here and the container fails to start — the correct,
# loud failure, rather than a service that answers "address not found" for
# every request.
_geosupport = Geosupport()


@app.get("/health")
def health():
    """Report the pinned Geosupport release. Reachability + release check."""
    return jsonify({"release": RELEASE})


@app.post("/resolve")
def resolve():
    """Resolve one address, returning Geosupport's raw response verbatim.

    Accepts ``house_number`` / ``street_name`` / ``borough`` (the borough code
    ``1``–``5`` the client sends). Returns the raw ``address()`` response on
    success, and the raw ``.result`` payload on a non-``'00'`` GRC — never a
    5xx for an ordinary geocoding failure, because those failures are data the
    client interprets (street-not-found, no-tax-lot, ambiguous), not errors.
    """
    body = request.get_json(silent=True) or {}
    try:
        result = _geosupport.address(
            house_number=body.get("house_number"),
            street_name=body.get("street_name"),
            borough=body.get("borough"),
        )
    except GeosupportError as exc:
        # Non-'00' GRC. The full response — GRC, Reason Code, Message, and any
        # List of Street Names — is on .result; hand it back untouched.
        result = exc.result
    return jsonify(result)


if __name__ == "__main__":
    # waitress rather than Flask's dev server: production-grade WSGI with no
    # "development server" warning, still trivial for a single-purpose sidecar.
    serve(app, host="0.0.0.0", port=8080)
