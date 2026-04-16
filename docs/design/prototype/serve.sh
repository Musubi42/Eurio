#!/usr/bin/env bash
set -e
PROTO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PROTO_DIR/../../.." && pwd)"

if [ ! -f "$PROTO_DIR/data/eurio_referential.json" ]; then
  echo "data/eurio_referential.json manquant. Lance ./setup-data.sh d'abord."
  exit 1
fi
echo "Eurio prototype -> http://localhost:8000/docs/design/prototype/"
echo "ngrok : dans un autre terminal -> ngrok http 8000"
cd "$REPO_ROOT"
python3 -m http.server 8000
