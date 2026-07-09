BOROUGH_FROM_BBL = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


def normalize_bbl(row: dict) -> str | None:
    """Return a 10-digit BBL string from a source row.

    Prefers a pre-formed bbl field; reconstructs from boroid/block/lot
    components when bbl is blank or absent. Returns None if data is
    insufficient. BBL-first borough derivation (see borough_from_bbl)
    is always correct for valid BBLs — do not use source borough strings.
    """
    bbl = (row.get("bbl") or "").strip()
    if len(bbl) == 10:
        return bbl
    boroid = str(row.get("boroid") or "").strip()
    block  = str(row.get("block")  or "").strip()
    lot    = str(row.get("lot")    or "").strip()
    if boroid and block and lot:
        return boroid.zfill(1) + block.zfill(5) + lot.zfill(4)
    return None


def borough_from_bbl(bbl: str) -> str | None:
    """Derive borough name from the first digit of a 10-digit BBL (ADR-002)."""
    return BOROUGH_FROM_BBL.get(bbl[0]) if bbl else None
