# SafeCross AI as a Progressive Web App

An installable, mobile-friendly version of the app. Same core as the Streamlit version (route comparison first, a separate risk
map, an intro tour, Westchester as an unvalidated estimate), but a real web app: it has a manifest and a service worker, so it can be
installed to a phone or desktop, opens instantly, and shows a friendly message when offline.

## How it is put together
```
pwa/
  server/   Flask API + static host. Reuses app/safecross_core.py and app/route_utils.py (no Streamlit needed)
  web/      the installable front end: index.html, manifest.webmanifest, sw.js, css/, js/, icons/
  tools/    make_icons.py regenerates the icons
```
Streamlit can't be a PWA (it doesn't expose a manifest or service worker), so this is a separate front end over the same Python logic.

## Run it locally
```
pip install -r pwa/requirements.txt
export GOOGLE_ROUTES_API_KEY=...        # see ROUTE_FINDER_SETUP.md for how to create and restrict the two keys
export GOOGLE_MAPS_JS_API_KEY=...
python pwa/server/server.py             # http://localhost:8000
```
`localhost` counts as secure, so the service worker and install prompt work there. Before this works you need the same files the Streamlit
app needs: `models/safecross_model_bundle.joblib`, `models/safecross_model_metadata.json`, and `data/sample/safecross_app_demo.csv`
(plus `safecross_app_demo_westchester.csv` for Westchester).

## Deploy (HTTPS is required to install a PWA)
Streamlit Community Cloud can't host this. Any host that runs a container or a Python web process works (Render, Fly.io, Railway,
Google Cloud Run...). Build from the repository root: `docker build -f pwa/Dockerfile -t safecross-pwa .` Then set the environment
variables from `pwa/.env.example` in the host's dashboard and turn on `TRUST_PROXY=1`. Add your site's address to the browser key's
website restrictions in Google Cloud.

## What makes it installable
- `manifest.webmanifest`: name, 192 and 512 icons (plus a maskable one for Android), `display: standalone`, theme colours, shortcuts.
  The server sends it as `application/manifest+json`; a wrong content type makes installability fail silently.
- `sw.js`: served from the site root with `Cache-Control: no-cache`; the server stamps a hash of the web files into it so every deploy
  becomes a new version, and users are offered a "Refresh" prompt.
- Chrome, Edge and Android show an **Install app** button. Safari on iPhone and iPad has no install prompt: the app shows a tip to use
  Share, then Add to Home Screen.

## What works offline, and what doesn't
The app opens offline (shell, styles, scripts, icons are cached) and says so. **Routes and the map need a connection**, by design:
Google Maps Platform restricts caching route content, and the Google Map itself loads from Google. The service worker never caches
`/api/*` or any Google request, and the app keeps route results in memory only.

## Google Maps Platform rules this follows
- Routes shown on a Google Map (Maps JavaScript API); route data fetched server-side with a key the browser never sees.
- No caching or storing of route content (service worker, localStorage and the server all leave it alone; every API response is `no-store`).
- Terms of use and privacy section on the About page referencing Google's terms. It is a draft: set `CONTACT_EMAIL` and have it reviewed.

## Protecting your Google bill
The server limits each client to `RATE_LIMIT_PER_HOUR` searches and everyone to `DAILY_ROUTE_CAP` per day. Also set quotas and a budget alert
in Google Cloud. The in-memory limiter assumes one server process (the Dockerfile uses one worker).

## Not done / worth knowing
- No Content-Security-Policy header: Google Maps needs a long, easy-to-get-wrong allow-list, and a mistake would break the map. Add one
  after testing it in a real browser.
- Not tested in a real browser or against the real Google APIs (see the notes in the hand-off message).

## Street names, sidewalks and other intersection facts
The app shows intersections as "Broadway & West 42nd Street" and lists facts such as the speed limit, sidewalk, bike lane, lighting,
traffic control and recent crashes. The street names and the sidewalk, bike-lane, lighting, bridge/tunnel and roundabout facts are not in
the model's data, so they come from a separate table you build once from the street-network files Notebook 1 saved:

```
python scripts/build_intersection_info.py            # writes data/sample/intersection_info.csv
python scripts/build_intersection_info.py --refresh-tags   # optional: also download sidewalk / bike-lane / lighting tags (slow, needs internet)
```
Restart the server afterwards. Without the file the app still works, but labels show coordinates ("Intersection near 40.7580, -73.9855") and
those extra facts read "not mapped". OpenStreetMap's default download leaves out sidewalk, bike-lane and lighting tags, so run
`--refresh-tags` once if you want them. Even then, "not mapped in OpenStreetMap" means nobody recorded it, not that it is missing.

## The route risk score
Each route gets a score that adds up the relative risk of EVERY intersection it passes (see the notes at the top of `app/route_utils.py`):
`closeness x vulnerability x risk_index`, summed. `risk_index` is the model's prediction divided by the area average (1.0 = average intersection).
Lower is safer. The walking/cycling adjustments (faster roads and recent pedestrian/cyclist injury crashes count more) are judgement calls, not
fitted values; their constants are in `route_utils.py`.
