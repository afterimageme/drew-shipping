#!/usr/bin/env bash
# Sync packages.json into index.html and push to GitHub if changed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PACKAGES_FILE="${1:-packages.json}"

echo "==> Syncing packages from $PACKAGES_FILE"

if [ ! -f "$PACKAGES_FILE" ]; then
    echo "Error: $PACKAGES_FILE not found"
    exit 1
fi

# Run the sync script
python3 sync.py "$PACKAGES_FILE"

# Check if there are changes to commit
if git diff --quiet index.html 2>/dev/null; then
    echo "==> No changes to index.html, nothing to push."
    exit 0
fi

echo "==> Changes detected, committing..."
git add index.html packages.json
git commit -m "Update package tracking data

Synced $(python3 -c "import json; print(len(json.load(open('$PACKAGES_FILE'))))"
) packages from $PACKAGES_FILE"

echo "==> Pushing to GitHub..."
git push

echo "==> Done. Dashboard updated."
