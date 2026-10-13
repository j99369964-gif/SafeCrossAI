"""SafeCross AI: API server and static host for the Progressive Web App.

    gunicorn "server:create_app()" --chdir pwa/server        # production (see pwa/Dockerfile)
    python pwa/server/server.py                              # local development, http://localhost:8000

What it does
* Serves the installable web app in pwa/web (with the correct manifest and service-worker headers).
* POST /api/routes asks Google's Routes API (server side, key never sent to the browser) and ranks the options by travel
  time and by how many high-risk intersections each passes.
* GET  /api/explore/*, /api/intersections/<id>: the risk map data.

Google Maps Platform policy (see app/route_utils.py): route results are never cached or stored here, every API response is
`Cache-Control: no-store`, and the browser draws routes on a Google Map.

Configuration (environment variables)
    GOOGLE_ROUTES_API_KEY    server-side key, restricted to the Routes API
    GOOGLE_MAPS_JS_API_KEY   browser key, restricted to the Maps JavaScript API and your site's web addresses
    RATE_LIMIT_PER_HOUR      route searches per client per hour (default 20)
    DAILY_ROUTE_CAP          route searches for everyone per day (default 500)
    TRUST_PROXY              "1" if behind a reverse proxy that sets X-Forwarded-For (most hosts)
    CONTACT_EMAIL            shown in the Terms and privacy section of the About page
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

from safecross_data import SafeCrossData, TIER_ORDER  # noqa: E402  (also puts app/ on sys.path)
from route_utils import (  # noqa: E402
    TIER_ELEVATED,
    TIER_HIGH,
    TRAVEL_MODES,
    RoutingError,
    analyze_route,
    build_map_payload,
    compare_routes,
    fetch_routes,
    format_distance,
    format_duration,
    google_maps_directions_url,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ROUTE_COLORS = ["#1a73e8", "#e8710a", "#188038", "#9334e6"]
MAX_TEXT_LENGTH = 200
VERSION = "1.0.0"


# =============================================================================
# Rate limiting (in memory; fine for one process. Use a shared store if you run several workers)
# =============================================================================
class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.time):
        self.limit, self.window, self.clock = limit, window_seconds, clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit if allowed. Returns (allowed, seconds_until_next_allowed)."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 5000:  # drop idle clients so memory stays bounded
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    self._hits.pop(stale, None)
            return True, 0


class DailyCap:
    def __init__(self, cap: int, clock: Callable[[], float] = time.time):
        self.cap, self.clock, self._day, self._count = cap, clock, None, 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        day = int(self.clock() // 86400)
        with self._lock:
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.cap:
                return False
            self._count += 1
            return True


# =============================================================================
# Trip result -> JSON
# =============================================================================
def split_bold(text: str) -> list[list]:
    """'a **b** c' -> [['a ', False], ['b', True], [' c', False]] so the browser can bold safely without innerHTML."""
    parts = text.split("**")
    return [[piece, index % 2 == 1] for index, piece in enumerate(parts) if piece]


def trip_warnings(routes, risks, index) -> dict:
    start_inside = index.contains(float(routes[0].points[0, 0]), float(routes[0].points[0, 1]))
    end_inside = index.contains(float(routes[0].points[-1, 0]), float(routes[0].points[-1, 1]))
    lowest = min(risk.coverage for risk in risks)
    outside = (not (start_inside and end_inside)) or lowest < 0.5
    return {
        "outside": bool(outside),
        "lowCoverage": None if (outside or lowest >= 0.8) else round(float(lowest), 2),
        "unvalidated": bool(any(risk.n_unvalidated for risk in risks)),
    }


def serialize_trip(routes, risks, comparison, notices, index, origin, destination, mode_code) -> dict:
    fastest = routes[comparison.fastest_idx]
    fastest_risk = risks[comparison.fastest_idx]
    cards = []
    for position, (route, risk) in enumerate(zip(routes, risks)):
        flagged = risk.passed.loc[risk.passed["risk_tier"].isin([TIER_HIGH, TIER_ELEVATED])]
        details = []
        for row in flagged.itertuples(index=False):
            validated = bool(getattr(row, "validated", True))
            details.append(
                {
                    "label": str(getattr(row, "intersection_label", getattr(row, "node_id", ""))),
                    "tier": 0 if row.risk_tier == TIER_HIGH else 1,
                    "pct": None if getattr(row, "risk_percentile", None) is None else int(round(float(row.risk_percentile))),
                    "area": str(getattr(row, "region_label", "")),
                    "unvalidated": not validated,
                    "miles": round(float(row.distance_along_route_m) / 1609.344, 2),
                }
            )
        is_fastest = position == comparison.fastest_idx
        cards.append(
            {
                "label": route.label,
                "color": ROUTE_COLORS[position % len(ROUTE_COLORS)],
                "minutes": int(max(round(route.duration_s / 60), 1)),
                "durationText": format_duration(route.duration_s),
                "distanceText": format_distance(route.distance_m),
                "nHigh": int(risk.n_high),
                "nElevated": int(risk.n_elevated),
                "nIntersections": int(risk.n_intersections),
                "nUnvalidated": int(risk.n_unvalidated),
                "badges": comparison.badges[position],
                "deltaMinutes": None if is_fastest else int(round((route.duration_s - fastest.duration_s) / 60)),
                "deltaHigh": None if is_fastest or risk.n_high == fastest_risk.n_high else int(risk.n_high - fastest_risk.n_high),
                "flagged": details,
            }
        )
    return {
        "routes": cards,
        "headline": split_bold(comparison.headline),
        "recommended": int(comparison.recommended_idx),
        "fastest": int(comparison.fastest_idx),
        "notices": list(notices),
        "warnings": trip_warnings(routes, risks, index),
        "map": build_map_payload(routes, risks, ROUTE_COLORS),
        "googleMapsUrl": google_maps_directions_url(origin, destination, mode_code),
        "snapshotWeek": index.snapshot_week,
    }


# =============================================================================
# App factory
# =============================================================================
def web_build_id(web_dir: Path) -> str:
    """Changes whenever any web asset changes, so the service worker updates itself on every deploy."""
    digest = hashlib.sha256()
    for path in sorted(p for p in web_dir.rglob("*") if p.is_file() and p.name != "sw.js"):
        digest.update(str(path.relative_to(web_dir)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def create_app(config: dict | None = None) -> Flask:
    env = os.environ
    cfg = {
        "repo_root": Path(__file__).resolve().parent.parent.parent,
        "routes_api_key": env.get("GOOGLE_ROUTES_API_KEY", ""),
        "maps_js_key": env.get("GOOGLE_MAPS_JS_API_KEY", ""),
        "rate_limit_per_hour": int(env.get("RATE_LIMIT_PER_HOUR", "20")),
        "daily_route_cap": int(env.get("DAILY_ROUTE_CAP", "500")),
        "trust_proxy": env.get("TRUST_PROXY", "0") == "1",
        "contact_email": env.get("CONTACT_EMAIL", ""),
        "http_post": requests.post,
        "clock": time.time,
        "data": None,
        "web_dir": WEB_DIR,
    }
    cfg.update(config or {})

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024  # request bodies here are tiny
    data: SafeCrossData = cfg["data"] or SafeCrossData(cfg["repo_root"])
    web_dir: Path = Path(cfg["web_dir"])
    limiter = SlidingWindowLimiter(cfg["rate_limit_per_hour"], 3600, cfg["clock"])
    daily = DailyCap(cfg["daily_route_cap"], cfg["clock"])
    build_id = web_build_id(web_dir)

    def error(message: str, status: int, **headers):
        response = jsonify({"error": message})
        response.status_code = status
        for key, value in headers.items():
            response.headers[key.replace("_", "-")] = str(value)
        return response

    def client_id() -> str:
        if cfg["trust_proxy"]:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.remote_addr or "unknown"

    # ------------------------------------------------------------------ API
    @app.get("/api/config")
    def api_config():
        return jsonify(
            {
                "version": VERSION,
                "mapsJsKey": cfg["maps_js_key"] or None,  # a BROWSER key, public by design (restrict it in Google Cloud)
                "routesConfigured": bool(cfg["routes_api_key"]),
                "contactEmail": cfg["contact_email"] or None,
                "snapshotWeek": data.snapshot_week,
                "areas": data.areas,
                "tiers": TIER_ORDER,
                "bounds": data.bounds,
                "maxPoints": 1500,
            }
        )

    @app.post("/api/routes")
    def api_routes():
        if not cfg["routes_api_key"]:
            return error("Route planning isn't set up on this server yet.", 503)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error("Send a JSON body with origin, destination and mode.", 400)
        origin, destination = body.get("origin"), body.get("destination")
        mode = body.get("mode", "Driving")
        if not all(isinstance(value, str) for value in (origin, destination, mode)):
            return error("Origin, destination and mode must be text.", 400)
        origin, destination = origin.strip(), destination.strip()
        if not origin or not destination:
            return error("Enter both a starting point and a destination.", 400)
        if len(origin) > MAX_TEXT_LENGTH or len(destination) > MAX_TEXT_LENGTH:
            return error(f"Places must be {MAX_TEXT_LENGTH} characters or fewer.", 400)
        mode_code = TRAVEL_MODES.get(mode) or (mode if mode in TRAVEL_MODES.values() else None)
        if mode_code is None:
            return error("Travel mode must be Driving, Cycling or Walking.", 400)

        allowed, retry_after = limiter.check(client_id())
        if not allowed:
            return error("You've searched a lot recently. Please wait a bit and try again.", 429, Retry_After=retry_after)
        if not daily.take():
            return error("The daily route-search limit has been reached. Please try again tomorrow.", 503)

        try:
            routes, notices = fetch_routes(cfg["routes_api_key"], origin, destination, mode_code, http_post=cfg["http_post"])
        except RoutingError as problem:
            return error(str(problem), 422)
        risks = [analyze_route(route, data.index) for route in routes]
        comparison = compare_routes(routes, risks)
        return jsonify(serialize_trip(routes, risks, comparison, notices, data.index, origin, destination, mode_code))

    def parse_filters():
        area_arg = request.args.get("areas")
        tier_arg = request.args.get("tiers")
        areas = [a for a in area_arg.split(",") if a] if area_arg is not None else None
        try:
            tiers = [int(t) for t in tier_arg.split(",") if t != ""] if tier_arg is not None else None
        except ValueError:
            return None, None, error("tiers must be numbers 0-3 separated by commas.", 400)
        if tiers is not None and any(t not in (0, 1, 2, 3) for t in tiers):
            return None, None, error("tiers must be numbers 0-3 separated by commas.", 400)
        return areas, tiers, None

    @app.get("/api/explore/summary")
    def api_summary():
        return jsonify(data.summary())

    @app.get("/api/explore/grid")
    def api_grid():
        areas, tiers, problem = parse_filters()
        return problem or jsonify(data.grid(areas, tiers))

    @app.get("/api/explore/points")
    def api_points():
        areas, tiers, problem = parse_filters()
        if problem:
            return problem
        try:
            south, north, west, east = (float(request.args[k]) for k in ("south", "north", "west", "east"))
            limit = int(request.args.get("limit", 1500))
        except (KeyError, ValueError):
            return error("south, north, west and east (numbers) are required.", 400)
        if south > north or west > east:
            return error("The viewport is inverted.", 400)
        return jsonify(data.points(south, north, west, east, areas, tiers, limit))

    @app.get("/api/intersections/<node_id>")
    def api_intersection(node_id):
        detail = data.intersection(node_id)
        return jsonify(detail) if detail else error("That intersection wasn't found.", 404)

    @app.get("/api/model")
    def api_model():
        return jsonify(data.model_info())

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "intersections": int(len(data.frame)), "version": VERSION})

    # ------------------------------------------------------------------ the web app itself
    @app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html", mimetype="text/html", max_age=0)

    @app.get("/sw.js")
    def service_worker():
        # Served from the site root so it can control the whole app; the build id makes every deploy a new worker.
        text = (web_dir / "sw.js").read_text(encoding="utf-8").replace("__BUILD_ID__", build_id)
        response = Response(text, mimetype="text/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/manifest.webmanifest")
    def manifest():
        response = send_from_directory(web_dir, "manifest.webmanifest", mimetype="application/manifest+json", max_age=0)
        return response

    @app.get("/<path:filename>")
    def static_files(filename):
        if filename == "api/routes":  # a GET to a POST-only endpoint is "wrong method", not "missing"
            return error("Method not allowed.", 405)
        if filename.startswith("api/"):
            return error("Not found.", 404)
        response = send_from_directory(web_dir, filename)
        # Icons never change under the same name; code and styles are revalidated (the service worker caches them anyway).
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if filename.startswith("icons/") else "no-cache"
        return response

    # ------------------------------------------------------------------ headers and errors
    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Google's referrer-restricted browser key needs the site origin to be sent with map requests.
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(404)
    def not_found(_):
        return error("Not found.", 404) if request.path.startswith("/api/") else Response("Not found", 404)

    @app.errorhandler(405)
    def not_allowed(_):
        return error("Method not allowed.", 405)

    @app.errorhandler(413)
    def too_large(_):
        return error("That request is too large.", 413)

    @app.errorhandler(500)
    def server_error(_):
        return error("Something went wrong on the server.", 500)

    app.extensions["safecross"] = {"data": data, "limiter": limiter, "daily": daily, "build_id": build_id}
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
