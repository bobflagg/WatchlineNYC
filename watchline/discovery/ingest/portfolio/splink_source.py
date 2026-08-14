"""
SplinkSource — probabilistic record linkage for the portfolio pipeline (Stage 2).

Replaces WoW's rule-based ``landlords_with_connections`` matching with Splink
(Fellegi-Sunter). It extracts *raw* HPD owner-contact records, normalizes them
lightly, and links them into resolved landlord entities using fuzzy comparisons
+ (in the full run) term-frequency weighting -- which recovers the geocode/typo
splits the address-gated rules cannot (e.g. Croman's "4 WEST 51 STREET", a
dropped "42"; Rashad's "666 BROADAWAY").

DB-agnostic: ``extract()`` takes any psycopg2 connection -- the raw HPD tables
(``hpd_contacts`` / ``hpd_registrations``) exist in both the WoW and JustFix
databases. Linkage runs on DuckDB in-process.

Design notes:
  * Grain = one row per distinct (kind, name, raw business address) identity,
    with ``bbls`` aggregated -- so term frequency reflects name rarity, not
    portfolio size, and the fragments WoW split are preserved for Splink to link.
  * Source = raw ``hpd_contacts`` (not ``wow_landlords``): the raw components
    still carry the shared house/street/zip that Geosupport had blanked.
  * ``DISTINCT ON (bbl)`` most-recent registration kills the multi-building
    fan-out; a registration covering several BBLs spreads to each.
  * Heavy address standardization (Geosupport/libpostal) is a later step that
    *adds* columns; Splink compares raw AND standardized, so a geocode failure
    never blanks the comparison.
"""
from __future__ import annotations

import pandas as pd

# The owner roles WoW keeps; agents/managers are excluded (shared across
# unrelated landlords -> false links via registered-agent addresses).
OWNER_ROLES = "{HeadOfficer,IndividualOwner,CorporateOwner,JointOwner}"

# `__WHERE__` is replaced (not %-parameterized) so callers can inject a slice
# predicate over the `c.` contact alias, e.g. "random() < 0.004" or a name list.
EXTRACT_SQL = r"""
WITH chosen_reg AS (                         -- most-recent registration per BBL (no fan-out)
  SELECT DISTINCT ON (btrim(r.bbl)) btrim(r.bbl) AS bbl, r.registrationid
  FROM hpd_registrations r
  WHERE r.bbl IS NOT NULL
  ORDER BY btrim(r.bbl), r.registrationenddate DESC NULLS LAST, r.lastregistrationdate DESC NULLS LAST
),
obs AS (                                     -- one row per (bbl, qualifying owner contact)
  SELECT cr.bbl, c.type AS role,
    NULLIF(upper(btrim(c.firstname)),'')            AS first_name,
    NULLIF(upper(btrim(c.lastname)),'')             AS last_name,
    NULLIF(upper(btrim(c.corporationname)),'')      AS corp_name,
    NULLIF(upper(btrim(c.businesshousenumber)),'')  AS biz_house,
    NULLIF(upper(btrim(c.businessstreetname)),'')   AS biz_street,
    NULLIF(upper(btrim(c.businessapartment)),'')    AS biz_apt,
    NULLIF(upper(btrim(c.businesscity)),'')         AS biz_city,
    NULLIF(upper(btrim(c.businessstate)),'')        AS biz_state,
    NULLIF(btrim(c.businesszip),'')                 AS biz_zip
  FROM chosen_reg cr
  JOIN hpd_contacts c ON c.registrationid = cr.registrationid
  WHERE c.type = ANY('{HeadOfficer,IndividualOwner,CorporateOwner,JointOwner}')
    AND (c.firstname IS NOT NULL OR c.lastname IS NOT NULL OR c.corporationname IS NOT NULL)
    AND (c.businesshousenumber IS NOT NULL OR c.businessstreetname IS NOT NULL)
    AND length(concat(c.businesshousenumber, c.businessstreetname)) > 2
    AND (__WHERE__)
),
rec AS (
  SELECT
    CASE WHEN first_name IS NOT NULL OR last_name IS NOT NULL THEN 'person' ELSE 'org' END AS contact_kind,
    COALESCE(NULLIF(trim(concat_ws(' ', first_name, last_name)),''), corp_name)             AS name_full,
    first_name, last_name,
    CASE WHEN first_name IS NOT NULL OR last_name IS NOT NULL THEN corp_name END            AS assoc_corp,
    trim(both ' ,' from regexp_replace(
      COALESCE(NULLIF(trim(concat_ws(' ', first_name, last_name)),''), corp_name, ''),
      ',?\s*(LLC|L\.L\.C\.|INC\.?|CORP\.?|LTD\.?|L\.P\.|LLP|PLLC|P\.C\.|LP|PC)\s*$','','i')) AS name_normalized,
    biz_house, biz_street, biz_apt,
    NULLIF(regexp_replace(coalesce(biz_apt,''),'\D','','g'),'')                             AS biz_apt_num,
    biz_city, biz_state, biz_zip, bbl, role
  FROM obs
)
SELECT
  md5(contact_kind||'|'||coalesce(name_full,'')||'|'||
      concat_ws('|', biz_house, biz_street, biz_apt, biz_zip, biz_city, biz_state)) AS unique_id,
  contact_kind, name_full, first_name, last_name, name_normalized,
  biz_house, biz_street, biz_apt, biz_apt_num, biz_city, biz_state, biz_zip,
  regexp_replace(biz_street,
    '\s+(STREET|ST|AVENUE|AVE|PLACE|PL|BOULEVARD|BLVD|ROAD|RD|LANE|LN|DRIVE|DR|COURT|CT|PARKWAY|PKWY|TERRACE|TER)$',
    '') AS biz_street_norm,
  left(first_name, 1)                                    AS first_initial,
  count(DISTINCT bbl)                                     AS n_bbls,
  array_agg(DISTINCT bbl ORDER BY bbl)                   AS bbls,
  array_remove(array_agg(DISTINCT assoc_corp), NULL)     AS assoc_corps
FROM rec
GROUP BY contact_kind, name_full, first_name, last_name, name_normalized,
         biz_house, biz_street, biz_apt, biz_apt_num, biz_city, biz_state, biz_zip
"""

# A (house, street) shared by more than this many distinct landlords is treated as
# an aggregator/registered-agent address and its address evidence is dropped. Tuned
# for full-population degrees (WoW's MAX_ADDR_DEGREE is 50 over its node set).
AGGREGATOR_DEGREE = 25

# Columns Splink compares (scalars only; bbls/assoc_corps ride along as payload).
COMPARISON_COLS = ["unique_id", "contact_kind", "name_full", "first_name", "last_name",
                   "name_normalized", "biz_house", "biz_street", "biz_street_norm",
                   "first_initial", "biz_apt_num", "biz_zip"]


def extract(conn, where: str = "TRUE") -> pd.DataFrame:
    """Run the extraction, returning one row per owner-contact identity.

    ``where`` is a SQL predicate over the ``c`` contact alias used to slice the
    population (e.g. ``"random() < 0.004"``). It is trusted internal SQL, not
    user input.
    """
    sql = EXTRACT_SQL.replace("__WHERE__", where)
    return pd.read_sql(sql, conn)   # no params -> LIKE '%' in `where` stays literal


# Distinct landlords per (house, normalized street) across the WHOLE owner-contact
# population — the aggregator signal. Computed unfiltered (no slice), so masking is
# production-correct rather than depending on what happens to be in a sample. The
# street-suffix regex MUST match biz_street_norm in EXTRACT_SQL so the join lines up.
ADDR_DEGREE_SQL = r"""
SELECT h AS biz_house, s AS biz_street_norm, count(DISTINCT who) AS addr_degree
FROM (
  SELECT DISTINCT
    upper(btrim(c.firstname)) || '|' || upper(btrim(c.lastname))          AS who,
    NULLIF(upper(btrim(c.businesshousenumber)),'')                        AS h,
    regexp_replace(NULLIF(upper(btrim(c.businessstreetname)),''),
      '\s+(STREET|ST|AVENUE|AVE|PLACE|PL|BOULEVARD|BLVD|ROAD|RD|LANE|LN|DRIVE|DR|COURT|CT|PARKWAY|PKWY|TERRACE|TER)$',
      '')                                                                 AS s
  FROM hpd_contacts c
  WHERE c.type = ANY('{HeadOfficer,IndividualOwner,CorporateOwner,JointOwner}')
    AND (c.firstname IS NOT NULL OR c.lastname IS NOT NULL)
    AND (c.businesshousenumber IS NOT NULL OR c.businessstreetname IS NOT NULL)
) t
WHERE h IS NOT NULL AND s IS NOT NULL
GROUP BY h, s
"""


def address_degrees(conn) -> pd.DataFrame:
    """Full-population (house, biz_street_norm) -> distinct-landlord count. Pass to
    ``fit(addr_degrees=...)`` so the aggregator mask uses real degrees, not sample."""
    return pd.read_sql(ADDR_DEGREE_SQL, conn)


def fit(df: pd.DataFrame, *, addr_degrees: pd.DataFrame | None = None,
        aggregator_degree: int = AGGREGATOR_DEGREE, seed: int = 42):
    """Build + train the Splink model and return ``(linker, predictions)``.

    Predictions are made at a permissive threshold, so the caller can cluster at
    any higher threshold (e.g. to sweep against a gold set) without re-predicting.
    Pass ``addr_degrees`` (from :func:`address_degrees`) to mask on real full-
    population degrees; otherwise degree is computed within ``df`` (sample-only).
    """
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    d = df.copy()
    cols = COMPARISON_COLS

    # Aggregator down-weight (WoW's MAX_ADDR_DEGREE, applied as masking): an address
    # shared by many *distinct* landlords is a registered-agent / office building, not
    # a private office. Drop its address evidence so those records can only link on
    # name — same-name pairs still merge, different-name neighbours no longer do.
    if addr_degrees is not None:
        d = d.merge(addr_degrees, on=["biz_house", "biz_street_norm"], how="left")
        d["_deg"] = d["addr_degree"].fillna(0)
        d = d.drop(columns=["addr_degree"])
    else:
        d["_deg"] = d.groupby(["biz_house", "biz_street_norm"])["name_normalized"].transform("nunique")
    d.loc[d["_deg"] > aggregator_degree,
          ["biz_house", "biz_street", "biz_street_norm", "biz_zip", "biz_apt_num"]] = None
    d = d.drop(columns=["_deg"])

    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            # Term-frequency on names: a rare "CROMAN"/"RASHAD" match counts far more
            # than a common one — the lever WoW's rules lack. TF is computed over `df`,
            # so pass a representative population (mostly the random sample), not the
            # target-heavy slice, or every target name looks "common".
            cl.JaroWinklerAtThresholds("last_name", [0.92, 0.85]).configure(term_frequency_adjustments=True),
            cl.JaroWinklerAtThresholds("first_name", [0.92, 0.80]).configure(term_frequency_adjustments=True),
            # Component address (house Levenshtein for "4"/"424", street fuzzy for
            # "BROADWAY"/"BROADAWAY", zip exact + TF). Aggregator down-weighting is a
            # later refinement — the composite-address attempt broke merging.
            cl.LevenshteinAtThresholds("biz_house", [1, 2]),
            # Compare the *suffix-normalized* street ("WEST 21ST STREET" == "WEST 21ST")
            # so a tight fuzzy threshold still catches the common suffix gap without
            # loosening enough to fuse unrelated streets.
            cl.JaroWinklerAtThresholds("biz_street_norm", [0.92, 0.85]),
            cl.ExactMatch("biz_zip").configure(term_frequency_adjustments=True),
        ],
        # Safe blocking set from the sizing pass — never `biz_zip` alone (208M pairs).
        # First-initial gate: different-first-name namesakes at one address (ANDREA vs
        # FILIPPO, DIVYA vs JAMAL) are never even scored; STEVE/STEVEN, ZACH/ZACHARY
        # share an initial and still merge.
        blocking_rules_to_generate_predictions=[
            block_on("last_name", "first_initial"),
            block_on("biz_house", "biz_street_norm", "first_initial"),
        ],
        retain_intermediate_calculation_columns=True,
    )

    linker = Linker(d[cols], settings, db_api=DuckDBAPI())
    # Same name + same address is ~certainly a match — a good anchor for training.
    linker.training.estimate_probability_two_random_records_match(
        [block_on("first_name", "last_name", "biz_house", "biz_street_norm")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=2_000_000, seed=seed)
    # Two EM passes triangulate m: block on the name to learn the address weights,
    # block on the address to learn the name weights.
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("first_name", "last_name"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("biz_house", "biz_street_norm"))

    preds = linker.inference.predict(threshold_match_probability=0.5)
    return linker, preds


def cluster(linker, preds, threshold: float = 0.95) -> pd.DataFrame:
    """Cluster predictions into entities at ``threshold``; adds ``cluster_id``."""
    c = linker.clustering.cluster_pairwise_predictions_at_threshold(
        preds, threshold_match_probability=threshold)
    return c.as_pandas_dataframe()


def link(df: pd.DataFrame, *, threshold: float = 0.95, seed: int = 42):
    """Convenience: fit + cluster at one threshold. Returns ``(clusters_df, linker)``."""
    linker, preds = fit(df, seed=seed)
    return cluster(linker, preds, threshold), linker


def build_portfolios(df: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Splink clusters into resolved-entity portfolios — the entity ->
    portfolio stage. At the name+address level the entity *is* the portfolio: its
    building set is the union of its member records' ``bbls`` (this is what recovers
    Croman's / Rashad's WoW-split buildings into one portfolio). One row per entity:
    ``entity_id, name, n_records, n_bbls, bbls``."""
    m = clusters[["unique_id", "cluster_id"]].merge(
        df[["unique_id", "name_full", "bbls", "n_bbls"]], on="unique_id")
    rows = []
    for cid, g in m.groupby("cluster_id"):
        bbls = sorted({b for lst in g["bbls"] for b in (lst or [])})
        name = g.sort_values("n_bbls", ascending=False)["name_full"].iloc[0]
        rows.append({"entity_id": cid, "name": name, "n_records": len(g),
                     "n_bbls": len(bbls), "bbls": bbls})
    return (pd.DataFrame(rows).sort_values("n_bbls", ascending=False)
              .reset_index(drop=True))
