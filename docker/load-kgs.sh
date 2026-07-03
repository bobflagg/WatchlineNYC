#!/bin/bash

docker stop neo4j-domain neo4j-epistemic

# Load simple.dump into container 1
docker run --rm \
  -v neo4j-domain:/data \
  -v /Users/rflagg/Learning/Sabbatical/git/WatchlineNYC/dumps/domain:/dumps \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  neo4j:enterprise \
  neo4j-admin database load \
  --from-path=/dumps \
  --overwrite-destination=true \
  neo4j

# Load epistemic.dump into container 2
docker run --rm \
  -v neo4j-epistemic:/data \
  -v /Users/rflagg/Learning/Sabbatical/git/WatchlineNYC/dumps/epistemic:/dumps \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
  neo4j:enterprise \
  neo4j-admin database load \
  --from-path=/dumps \
  --overwrite-destination=true \
  neo4j

docker start neo4j-domain neo4j-epistemic