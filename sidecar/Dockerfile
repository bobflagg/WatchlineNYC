# Geosupport sidecar (decision D9).
#
# A thin HTTP wrapper around NYC DCP Geosupport Desktop Edition, so the agent —
# which runs natively on macOS / Python 3.13 — can resolve addresses through the
# same geocoder the ingestion pipeline uses. python-geosupport needs the
# Linux/Windows Geosupport binaries, so this image is linux/amd64 and runs under
# emulation on Apple Silicon (measured fine for single lookups; see
# specs/2026-07-30-phase-0-foundations/spike-findings.md §8).
#
# Build/run with an explicit platform flag rather than hardcoding it on FROM
# (which raises the FromPlatformFlagConstDisallowed lint warning):
#
#   docker build  --platform=linux/amd64 -t watchline-geosupport sidecar/
#   docker run -d --platform=linux/amd64 -p 8080:8080 --name geosupport watchline-geosupport
#
# The RELEASE/MAJOR/MINOR pin MUST match the ingestion pipeline's Geosupport
# release and geocode.REQUIRED_RELEASE. It is the one real coupling between
# agent-side and pipeline-side geocoding — a mismatch surfaces as inexplicably
# missing buildings, which is why /health reports it and the client fails loudly.
FROM python:3.10-slim

ENV RELEASE=25b
ENV MAJOR=25
ENV MINOR=2

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl unzip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /geosupport
RUN FILE_NAME=linux_geo${RELEASE}_${MAJOR}.${MINOR}.zip \
  && curl -sSO https://s-media.nyc.gov/agencies/dcp/assets/files/zip/data-tools/bytes/geosupport/$FILE_NAME \
  && unzip -q *.zip \
  && rm *.zip

ENV GEOFILES=/geosupport/version-${RELEASE}_${MAJOR}.${MINOR}/fls/
ENV LD_LIBRARY_PATH=/geosupport/version-${RELEASE}_${MAJOR}.${MINOR}/lib/

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8080
CMD ["python", "app.py"]
