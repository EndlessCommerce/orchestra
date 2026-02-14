#!/usr/bin/env bash
# Initialize sample-project as a git repo.
# Run this before using 'orchestra run add-tests.dot'.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$SCRIPT_DIR/sample-project"

if [ -d "$REPO/.git" ]; then
    echo "sample-project is already a git repo — skipping init."
    exit 0
fi

echo "Initializing sample-project as a git repo..."
cd "$REPO"
git init
git add .
git commit -m "Initial commit: calculator project"
echo "Done. You can now run: orchestra run add-tests.dot"
