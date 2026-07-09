-- Build the landlord graph: nodes (grouped contacts) and weighted edges
-- (name-based and address-based connections) for the WCC + Louvain pipeline.
--
-- Watchline adaptation of the JustFix WoW landlords_with_connections.sql:
--   - Added high-volume address exclusion using hpd_business_addresses.
--     Addresses with >= 50 contacts are management companies, registered
--     agents, or co-op buildings whose address would generate massive false
--     WCC components. These are excluded from address-based edge construction.
--     The threshold is configurable; review after the first full run.
--
-- Fix (2026-06-30): the original high_volume_addresses filter queried
--   hpd_business_addresses per apartment variant (e.g. '9FLOOR', '9', '9TFL').
--   Because the dominant variant at 575 Fifth Avenue was '9FLOOR' (3,182
--   contacts) rather than '9TH FLOOR' or the bare address, the filter
--   treated each variant in isolation and only the dominant variant cleared
--   the 50-contact threshold. The address was correctly blocked on that
--   variant, but the matching JOIN in matched_bizaddrs keys on bizhousestreet
--   alone (housenumber + streetname, no apartment), so the block was never
--   applied. The fix aggregates contacts across ALL apartment variants for the
--   same housenumber+streetname+zip before applying the threshold, and the
--   JOIN now also keys on housenumber+streetname+zip only, matching the
--   structure of wow_landlords.bizaddr.
--
--   RMT-002 amendment note: "A blocklist of known high-volume professional
--   addresses should be developed and applied as a filter."
--
-- Edge weight scheme (unchanged from JustFix):
--   Name-based:    base 1 + bizhousestreet_similarity (0.8-1.0) + 0.5 if apt matches
--   Address-based: base 2 + name_similarity (0-1)
--
-- Corresponds to ResolutionMethods RMT-001 (name) and RMT-002 (address).

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- High-volume address filter (RMT-002 filter)
--
-- Aggregates across ALL apartment variants for each housenumber+streetname+zip
-- before applying the >= 50-contact threshold. This prevents management
-- company addresses from evading the filter through apartment-field
-- fragmentation (e.g. '9FLOOR', '9', '9TFL', 'NINTH FL' all at the same
-- physical address).
--
-- The resulting table has one row per (housenumber, streetname, zip) and is
-- joined on those three columns only -- matching the bizhousestreet+bizzip
-- fields in wow_landlords, which do not include the apartment.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS high_volume_addresses;
CREATE TEMPORARY TABLE IF NOT EXISTS high_volume_addresses AS (
    SELECT
        businesshousenumber,
        businessstreetname,
        businesszip,
        SUM(numberofcontacts) AS total_contacts
    FROM hpd_business_addresses
    GROUP BY businesshousenumber, businessstreetname, businesszip
    HAVING SUM(numberofcontacts) >= 50
);
CREATE INDEX ON high_volume_addresses (businesshousenumber, businessstreetname, businesszip);

-- ---------------------------------------------------------------------------
-- Grouped landlord nodes
-- One row per unique (name, address) combination; bbls is the array of all
-- BBLs registered under this name/address pair.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS landlords_grouped;
CREATE TEMPORARY TABLE IF NOT EXISTS landlords_grouped AS (
    SELECT
        row_number() OVER () AS nodeid,
        name,
        -- Strip legal entity suffixes before name matching (RMT-001)
        trim(both ' ,' FROM
            regexp_replace(
                upper(trim(coalesce(name, ''))),
                ',?\s*(LLC|L\.L\.C\.|INC\.?|CORP\.?|LTD\.?|L\.P\.|LLP|PLLC|P\.C\.|LP|PC)\s*$',
                '',
                'i'
            )
        ) AS name_normalized,
        bizaddr,
        bizhousestreet,
        bizapt,
        regexp_replace(bizapt, '\D', '', 'g') AS bizaptnum,
        bizzip,
        array_agg(bbl) AS bbls
    FROM wow_landlords
    WHERE bbl IS NOT NULL
    GROUP BY name, bizaddr, bizhousestreet, bizapt, bizaptnum, bizzip
);

CREATE INDEX ON landlords_grouped (nodeid);
CREATE INDEX ON landlords_grouped (name);
CREATE INDEX ON landlords_grouped (name_normalized);
CREATE INDEX ON landlords_grouped (bizaddr);
CREATE INDEX ON landlords_grouped (bizzip);
CREATE INDEX ON landlords_grouped (bizhousestreet, bizaptnum);
CREATE INDEX ON landlords_grouped USING gin(bizhousestreet gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Name-based edges (RMT-001)
-- Exact normalized name match + same ZIP + high address similarity.
-- Excluded if either endpoint's address has >= 50 total contacts
-- (summed across all apartment variants at that housenumber+streetname+zip).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS matched_names;
CREATE TEMPORARY TABLE IF NOT EXISTS matched_names AS (
    SELECT
        orig.nodeid,
        matched.nodeid AS match_nodeid,
        coalesce(similarity(orig.bizhousestreet, matched.bizhousestreet), 0) AS bizhousestreet_similarity,
        coalesce((orig.bizaptnum = matched.bizaptnum)::int::numeric, 0) AS bizaptnum_similarity
    FROM landlords_grouped AS orig
    FULL JOIN landlords_grouped AS matched
           ON orig.name_normalized = matched.name_normalized
          AND orig.name_normalized != ''
    -- Exclude high-volume addresses from name-based edge sources.
    -- Join on housenumber+streetname+zip only (no apartment): the aggregate
    -- filter applies to the physical address regardless of unit formatting.
    LEFT JOIN high_volume_addresses hva_orig
           ON split_part(orig.bizhousestreet, ' ', 1) = hva_orig.businesshousenumber
          AND substr(orig.bizhousestreet,
                     length(split_part(orig.bizhousestreet, ' ', 1)) + 2)
              = hva_orig.businessstreetname
          AND orig.bizzip = hva_orig.businesszip
    LEFT JOIN high_volume_addresses hva_matched
           ON split_part(matched.bizhousestreet, ' ', 1) = hva_matched.businesshousenumber
          AND substr(matched.bizhousestreet,
                     length(split_part(matched.bizhousestreet, ' ', 1)) + 2)
              = hva_matched.businessstreetname
          AND matched.bizzip = hva_matched.businesszip
    WHERE orig.nodeid != matched.nodeid
      AND orig.bizzip = matched.bizzip
      AND hva_orig.businesshousenumber IS NULL    -- not a high-volume address
      AND hva_matched.businesshousenumber IS NULL -- not a high-volume address
      AND (
        similarity(orig.bizhousestreet, matched.bizhousestreet) > 0.9
        OR (
            similarity(orig.bizhousestreet, matched.bizhousestreet) > 0.8
            AND (orig.bizaptnum = matched.bizaptnum)
        )
      )
);

DROP TABLE IF EXISTS matched_names_agg;
CREATE TEMPORARY TABLE IF NOT EXISTS matched_names_agg AS (
    SELECT
        nodeid,
        json_agg(
            json_build_object(
                'nodeid', match_nodeid,
                'weight', (bizhousestreet_similarity + (bizaptnum_similarity * 0.5) + 1)::numeric
            )
        ) AS name_match_info
    FROM matched_names
    GROUP BY nodeid
);

-- ---------------------------------------------------------------------------
-- Address-based edges (RMT-002)
-- Exact house number + street name + ZIP match, tolerating missing apt.
-- Addresses present in the high-volume filter are excluded entirely:
-- both as sources and as targets.
-- Join on housenumber+streetname+zip only, matching the aggregate filter.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS matched_bizaddrs;
CREATE TEMPORARY TABLE IF NOT EXISTS matched_bizaddrs AS (
    SELECT
        orig.nodeid,
        matched.nodeid AS match_nodeid,
        coalesce(similarity(orig.name, matched.name), 0)::numeric AS name_similarity
    FROM landlords_grouped AS orig
    FULL JOIN landlords_grouped AS matched
           ON orig.bizhousestreet = matched.bizhousestreet
          AND (orig.bizaptnum = matched.bizaptnum OR orig.bizaptnum = '' OR matched.bizaptnum = '')
          AND orig.bizzip = matched.bizzip
    -- Exclude high-volume addresses from address-based edges entirely.
    -- Join on housenumber+streetname+zip only (no apartment).
    LEFT JOIN high_volume_addresses hva
           ON split_part(orig.bizhousestreet, ' ', 1) = hva.businesshousenumber
          AND substr(orig.bizhousestreet,
                     length(split_part(orig.bizhousestreet, ' ', 1)) + 2)
              = hva.businessstreetname
          AND orig.bizzip = hva.businesszip
    WHERE orig.nodeid != matched.nodeid
      AND hva.businesshousenumber IS NULL  -- not a high-volume address
);

DROP TABLE IF EXISTS matched_bizaddrs_agg;
CREATE TEMPORARY TABLE IF NOT EXISTS matched_bizaddrs_agg AS (
    SELECT
        nodeid,
        json_agg(
            json_build_object(
                'nodeid', match_nodeid,
                'weight', (name_similarity + 2)::numeric
            )
        ) AS bizaddr_match_info
    FROM matched_bizaddrs
    GROUP BY nodeid
);

-- ---------------------------------------------------------------------------
-- Final output: nodes with their edge lists
-- Returned directly as the query result; not persisted as a table.
-- load.py reads this result via cur.fetchall() after executing this file.
-- ---------------------------------------------------------------------------
SELECT
    l.nodeid,
    l.name,
    l.bizaddr,
    l.bbls,
    n.name_match_info,
    b.bizaddr_match_info
FROM landlords_grouped AS l
LEFT JOIN matched_names_agg AS n USING (nodeid)
LEFT JOIN matched_bizaddrs_agg AS b USING (nodeid)
ORDER BY l.nodeid;
