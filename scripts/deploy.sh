#!/usr/bin/env bash
# deploy.sh
# Copies all Watchline generated files from Claude's outputs into the
# WatchlineNYC project directory.
#
# Usage: bash deploy.sh
# Run from anywhere; paths are absolute.

set -euo pipefail

PROJECT="/Users/rflagg/Learning/Sabbatical/git/WatchlineNYC/watchline"
OUTPUTS="/mnt/user-data/outputs/watchline"

echo "Deploying to: $PROJECT"
echo ""

# ---------------------------------------------------------------------------
# fw/ — Python package files
# ---------------------------------------------------------------------------

FW_FILES=(
    "fw/state.py"
    "fw/connections.py"
    "fw/resolver.py"
    "fw/intent.py"
    "fw/router.py"
    "fw/narrator.py"
    "fw/renderer.py"
    "fw/investigator.py"
    "fw/server.py"
    "fw/intents/__init__.py"
    "fw/intents/base.py"
    "fw/intents/deterioration.py"
    "fw/intents/stubs.py"
)

for f in "${FW_FILES[@]}"; do
    src="$OUTPUTS/$f"
    dst="$PROJECT/$f"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  ✓ $f"
done

# ---------------------------------------------------------------------------
# fw/templates/ — HTML dashboard templates and CSS
# ---------------------------------------------------------------------------

TEMPLATE_FILES=(
    "fw/templates/watchline.css"
    "fw/templates/base.html"
    "fw/templates/intents/deterioration.html"
    "fw/templates/intents/stub.html"
)

for f in "${TEMPLATE_FILES[@]}"; do
    src="$OUTPUTS/$f"
    dst="$PROJECT/$f"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  ✓ $f"
done

# ---------------------------------------------------------------------------
# ui/ — Streamlit app
# ---------------------------------------------------------------------------

UI_FILES=(
    "ui/app.py"
)

for f in "${UI_FILES[@]}"; do
    src="$OUTPUTS/$f"
    dst="$PROJECT/$f"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  ✓ $f"
done

echo ""
echo "Deploy complete. Restart the FastAPI server and Streamlit app to pick up changes."
echo ""
echo "  Server:   uvicorn watchline.fw.server:app --reload"
echo "  Streamlit: streamlit run watchline/ui/app.py"
