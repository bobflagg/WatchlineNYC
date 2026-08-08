# Neo4j ENTERPRISE (evaluation license) + a first-boot seed step that loads the
# graph dump (local mount or Google Drive) as the default `neo4j` database.
#
# Enterprise is required: the source graph uses Neo4j's *block* store format, which
# is Enterprise-only. Community fails to load it ("Block format detected ...
# unavailable in this edition"). The eval license is accepted at runtime via
# NEO4J_ACCEPT_LICENSE_AGREEMENT (set in docker-compose.yml).
#
# Pin the SAME Neo4j version the dump was created with — a dump from a NEWER Neo4j
# fails to load ("newer version than the current binaries; downgrade is not
# supported"). This matches the source (Neo4j Desktop, `CALL dbms.components()`);
# bump it if your source reports a newer version.
FROM neo4j:2026.04.0-enterprise

# gdown handles Google Drive's large-file virus-scan confirmation, which plain
# curl/wget cannot. Kept in a venv so it never touches Neo4j's own runtime.
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-venv \
  && rm -rf /var/lib/apt/lists/* \
  && python3 -m venv /opt/gdown \
  && /opt/gdown/bin/pip install --no-cache-dir "gdown>=5.2.0"
ENV PATH="/opt/gdown/bin:${PATH}"

COPY seed-and-start.sh /usr/local/bin/seed-and-start.sh
RUN chmod +x /usr/local/bin/seed-and-start.sh

# Replace the entrypoint with the seed wrapper (it exec's the stock entrypoint).
ENTRYPOINT ["/usr/local/bin/seed-and-start.sh"]
