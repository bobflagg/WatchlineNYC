# Canonical batch sizes — ADR-010: adopt discovery's larger values.
BATCH_SIZE      = 2000  # rows per UNWIND batch written to Neo4j
CURSOR_ITERSIZE = 5000  # PostgreSQL server-side cursor fetchmany size
PORTFOLIO_BATCH = 200   # inner UNWIND in portfolio store (row count multiplied by sub-rows)
