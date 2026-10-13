# Host the PWA free from your own PC with Cloudflare Tunnel

Your PC runs the Flask server; Cloudflare gives it a public HTTPS address. Free, no router changes, no account needed for a quick tunnel.
The site is only up while your PC, the server and the tunnel are running.

## One-time setup (Windows)
1. Do the normal local setup first: `pip install -r pwa/requirements.txt`, and make sure `models/` and `data/sample/` have the model and demo CSVs
   (run `scripts/make_model_bundle.py` and `scripts/export_streamlit_assets.py`; for Westchester, `scripts/build_westchester_assets.py`).
2. Install the tunnel program: `winget install --id Cloudflare.cloudflared`, then close and reopen the terminal.
3. Copy `pwa\tunnel\keys.example.ps1` to `pwa\tunnel\keys.ps1` and paste in your two Google keys (see ROUTE_FINDER_SETUP.md).
   Mac/Linux: use `keys.example.env` -> `keys.env` and `start_mac_linux.sh` instead.

## Every time
From the repository root:
```
powershell -ExecutionPolicy Bypass -File pwa\tunnel\start_windows.ps1
```
After a few seconds cloudflared prints `https://something-random.trycloudflare.com`. Open that on any phone or computer. Ctrl+C stops both programs.

## Google key step (needed each time the address changes)
The browser key (Maps JavaScript API) is restricted to websites. Quick-tunnel addresses change every run, so either:
- add the new address under Application restrictions > Websites each time (strictest), or
- add `https://*.trycloudflare.com/*` once (easier, but any trycloudflare site could then use your browser key; that is why the next point matters).

Either way, set a low quota/budget alert on both keys in Google Cloud and keep `DAILY_ROUTE_CAP` small (it is 200 in the example). The server key is never sent to the browser.

## Things to know
- **The address changes every run**, so an installed PWA points at a dead address next time. For a demo, open it in the browser (or reinstall each session).
  For a permanent address you need a domain managed by Cloudflare and a named tunnel (`cloudflared tunnel login`, `create`, `route dns`, `run`); the tunnel
  itself is free, the domain is not (about $10/year).
- **Quick tunnels are for testing/demos.** Cloudflare gives no uptime promise, and they cap concurrent requests (about 200), plenty for a class demo.
- The server listens only on 127.0.0.1 when started by these scripts, so nobody on your Wi-Fi can reach it directly; all traffic goes through the tunnel.
- `TRUST_PROXY=1` makes the rate limiter see each visitor's real address. Do not set it when running without the tunnel.
- Keep `keys.ps1` / `keys.env` out of Git (the `.gitignore` in this folder covers them).
- Westchester is still shown as an unvalidated estimate; say so in your presentation.
