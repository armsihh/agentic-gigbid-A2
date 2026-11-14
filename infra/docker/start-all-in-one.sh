#!/bin/sh
# Start GigSim on localhost, then the API (which serves the web UI) on $PORT (Render sets PORT).
set -e
uvicorn gigsim.app:app --host 127.0.0.1 --port 8081 --log-level warning &
GIGSIM_PID=$!
for i in $(seq 1 60); do
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')" 2>/dev/null && break
  sleep 1
done
trap 'kill $GIGSIM_PID 2>/dev/null' EXIT
exec uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips '*'
