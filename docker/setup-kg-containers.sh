#!/bin/bash

docker rm --force neo4j-domain neo4j-epistemic 2>/dev/null || true

docker run -d \
  --name neo4j-domain \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/watchline \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  -v /Users/rflagg/Learning/Sabbatical/git/WatchlineNYC/dumps:/dumps \
  -v neo4j-domain:/data \
  neo4j:enterprise

docker run -d \
  --name neo4j-epistemic \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/watchline \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  -v /Users/rflagg/Learning/Sabbatical/git/WatchlineNYC/dumps:/dumps \
  -v neo4j-epistemic:/data \
  neo4j:enterprise
