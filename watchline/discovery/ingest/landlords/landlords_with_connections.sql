-- landlords_with_connections — the WoW landlord graph table, built from wow_landlords.
--
-- VENDORED VERBATIM from JustFix's Who Owns What
--   who-owns-what/portfoliograph/sql/landlords_with_connections.sql
-- (only the trailing read-only `SELECT * FROM landlords_with_connections` was dropped —
-- that statement exists purely so WoW's graph.py can stream the result set; we materialize
-- the table instead). Kept byte-faithful otherwise so our nodeids/edge weights match WoW's.
--
-- Source table `wow_landlords` is one contact per (bbl, registration) with a standardized
-- business address. We self-join it to build the connections (edges) between distinct
-- (name, bizaddr) contacts (nodes), keyed by a generated `nodeid`, and weight each edge by
-- our confidence — later consumed by the WCC + Louvain split. In justfixwow both the source
-- and this output live in the `wow` schema (the connecting user's schema is first on
-- search_path), so the unqualified names below resolve there.
--
-- http://blog.scoutapp.com/articles/2016/07/12/how-to-make-text-searches-in-postgresql-faster-with-trigram-similarity


CREATE EXTENSION IF NOT EXISTS pg_trgm;


DROP TABLE IF EXISTS landlords_grouped;
CREATE TEMPORARY TABLE IF NOT EXISTS landlords_grouped AS (
	SELECT
		row_number() OVER () AS nodeid,
		name,
		bizaddr,
		bizhousestreet,
		bizapt,
		regexp_replace(bizapt, '\D','','g') AS bizaptnum,
		bizzip,
		array_agg(bbl) AS bbls
	FROM wow_landlords
	WHERE bbl IS NOT NULL
	GROUP BY name, bizaddr, bizhousestreet, bizapt, bizaptnum, bizzip
);

CREATE INDEX ON landlords_grouped (nodeid);
CREATE INDEX ON landlords_grouped (name);
CREATE INDEX ON landlords_grouped (bizaddr);
CREATE INDEX ON landlords_grouped (bizzip);
CREATE INDEX ON landlords_grouped (bizhousestreet, bizaptnum);
CREATE INDEX ON landlords_grouped USING gin(bizhousestreet gin_trgm_ops);

DROP TABLE IF EXISTS landlords_with_connections;
CREATE TABLE IF NOT EXISTS landlords_with_connections AS
WITH matched_names AS (
	-- In general we are less confident in name matches, so only match if in
	-- addition to exact name match there is also a close partial match on
	-- bizaddr. We require matched zipcode, use similarity on number and street
	-- name, and compare only the numbers from the apt field since apt values
	-- aren't covered by geocoder standardization.
    SELECT
        orig.nodeid,
        matched.nodeid as match_nodeid,
        coalesce(similarity(orig.bizhousestreet, matched.bizhousestreet), 0) AS bizhousestreet_similarity,
		coalesce((orig.bizaptnum = matched.bizaptnum)::int::numeric, 0) AS bizaptnum_similarity
    FROM landlords_grouped AS orig
    FULL JOIN landlords_grouped AS matched USING(name)
    WHERE orig.nodeid != matched.nodeid
	  AND orig.bizzip = matched.bizzip
	  AND (
		similarity(orig.bizhousestreet, matched.bizhousestreet) > 0.9
		OR (
			similarity(orig.bizhousestreet, matched.bizhousestreet) > 0.8
			AND (orig.bizaptnum = matched.bizaptnum)
		)
	  )

), matched_names_agg AS (
	-- Since we are not confident in name matches generally, we start with a
	-- lower base score (1) and add the similarity score of number/street
	-- (0.8-0.99) and a small increase for matching apartment numerals (0.5)
	SELECT
		nodeid,
		json_agg(
			json_build_object(
				'nodeid', match_nodeid,
				'weight', (bizhousestreet_similarity + (bizaptnum_similarity * 0.5) + 1)::numeric)
		) AS name_match_info
	FROM matched_names
    GROUP BY nodeid

), matched_bizaddrs AS (
	-- Allow matches if exact on house number, street name, zipcode, and the
	-- numbers within the apt field. This allows matches when the only
	-- difference is "unit 12" vs "suite 12" or apt is missing entirely, since
	-- the geocoder standardization can't be applied to apt and these minor
	-- differences or missing values are common. We then also calculate the
	-- similarity between names for these address match cases.
    SELECT
        orig.nodeid,
        matched.nodeid AS match_nodeid,
        coalesce(similarity(orig.name, matched.name), 0)::numeric AS name_similarity
    FROM landlords_grouped AS orig
    FULL JOIN landlords_grouped AS matched
		ON orig.bizhousestreet = matched.bizhousestreet
		  AND (orig.bizaptnum = matched.bizaptnum OR orig.bizaptnum = '' OR matched.bizaptnum = '')
		  AND orig.bizzip = matched.bizzip
    WHERE orig.nodeid != matched.nodeid

), matched_bizaddrs_agg AS (
	-- Since we are more confident about exact biz address matches, we start
	-- with a higher base score (2) and add on score for partial name match
	-- (0-1).
	SELECT
		nodeid,
		json_agg(
			json_build_object('nodeid', match_nodeid, 'weight', (name_similarity + 2)::numeric)
		) AS bizaddr_match_info
	FROM matched_bizaddrs
    GROUP BY nodeid
)
SELECT
	nodeid,
	name,
	bizaddr,
	bbls,
	n.name_match_info,
	b.bizaddr_match_info
FROM landlords_grouped AS l
LEFT JOIN matched_names_agg AS n USING(nodeid)
LEFT JOIN matched_bizaddrs_agg AS b USING(nodeid)
ORDER BY nodeid;
