#!/usr/bin/env bash
set -e
PROTO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PROTO_DIR/../../.." && pwd)"

if [ ! -f "$PROTO_DIR/data/app_core.json" ]; then
  echo "data/app_core.json manquant. Lance 'go-task ml:build-app-core' d'abord."
  exit 1
fi
echo "Eurio prototype -> http://localhost:8000/docs/design/prototype/"
echo "ngrok : dans un autre terminal -> ngrok http 8000"
cd "$REPO_ROOT"
# No-cache server : sans ça, le navigateur ressert les vieilles scènes/JS et on
# audite une version périmée. Anti-cache sur toutes les réponses → un simple
# reload suffit toujours à voir le dernier proto.
exec python3 - <<'PY'
import http.server, socketserver
class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('', 8000), Handler) as httpd:
    httpd.serve_forever()
PY
