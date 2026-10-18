#!/usr/bin/env bash
# Run from the repository root:  bash pwa/tunnel/start_mac_linux.sh   (keys go in pwa/tunnel/keys.env)
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f pwa/tunnel/keys.env ] || { echo "Copy pwa/tunnel/keys.example.env to keys.env and fill it in."; exit 1; }
command -v cloudflared >/dev/null || { echo "Install cloudflared first (brew install cloudflared)."; exit 1; }
set -a; . pwa/tunnel/keys.env; set +a
export HOST=127.0.0.1 PORT=8000 TRUST_PROXY=1
python pwa/server/server.py & SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 5
echo "Look for the https://....trycloudflare.com address below."
cloudflared tunnel --url http://127.0.0.1:8000
