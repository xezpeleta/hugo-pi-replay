#!/bin/sh
# Serve the hugo-pi-replay example site on http://localhost:1313/
set -e
cd "$(dirname "$0")"
THEMES_DIR="$(cd .. && pwd)"
exec hugo server --source exampleSite --themesDir "$THEMES_DIR" --bind 0.0.0.0 "$@"
