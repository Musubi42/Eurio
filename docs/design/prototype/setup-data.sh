#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
SRC="../../../ml/datasets/eurio_referential.json"
if [ ! -f "$SRC" ]; then
  echo "Source manquante : $SRC"
  exit 1
fi
mkdir -p data
cp "$SRC" data/eurio_referential.json
SIZE=$(wc -c < data/eurio_referential.json | tr -d ' ')
COUNT=$(python3 -c "import json; d=json.load(open('data/eurio_referential.json')); print(d.get('entry_count', len(d.get('entries', []))))" 2>/dev/null || echo "?")
echo "Copie data/eurio_referential.json ($SIZE octets, $COUNT entries)"
