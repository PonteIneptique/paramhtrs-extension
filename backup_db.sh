#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/instance/lines.db"
DEST_DIR="$SCRIPT_DIR/../backup"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$DEST_DIR/lines_${TIMESTAMP}.db"

mkdir -p "$DEST_DIR"

# Use SQLite's online backup to get a consistent snapshot
sqlite3 "$SRC" ".backup '$DEST'"

echo "Backed up to $DEST"

# Remove backups older than 7 days
find "$DEST_DIR" -maxdepth 1 -name "lines_*.db" -mtime +7 -delete
