#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -f data/eurio_referential.json ]; then
  echo "data/eurio_referential.json manquant. Lance ./setup-data.sh d'abord."
  exit 1
fi
echo "Eurio prototype -> http://localhost:8000"
echo "ngrok : dans un autre terminal -> ngrok http 8000"
python3 -m http.server 8000
