"""Route-finding helpers for SafeCross AI.

Pure Python (NumPy / pandas / SciPy / requests). Nothing in here imports
Streamlit, so it is easy to test and safe to import from any page.

What this module does
---------------------
1. Asks the Google Routes API for route options between two places.
2. Decodes each route's geometry and finds the intersections it passes, using the
   same scored intersections the Explore map uses.
3. Summarises each route (travel time, distance, how many high-risk
   intersections it passes) and compares the options.

Google Maps Platform policy notes (read before changing this file)
-------------------------------------------------------------------
* Routes API results shown on a map must be shown on a Google Map
  (see route_map.py).
* Caching of most Routes API content is restricted. Nothing here caches or
  writes route results to disk; the Streamlit page keeps them only in the
  visitor's own session.
"""

from __future__ import annotations

import math
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree

# --- Google Routes API ----------------------------------------------------
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
# Only fields we use. (A response field mask is required by the API.)
ROUTES_FIELD_MASK = (
    "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.routeLabels"
)
REQUEST_TIMEOUT_S = 20
MAX_ROUTES = 4

TRAVEL_MODES = {"Driving": "DRIVE", "Cycling": "BICYCLE", "Walking": "WALK"}
MAPS_URL_MODES = {"DRIVE": "driving", "BICYCLE": "bicycling", "WALK": "walking"}

# --- Risk tiers: must match the labels app_utils.assign_risk_tier produces ---
TIER_HIGH = "Highest-priority (top 10%)"
TIER_ELEVATED = "Elevated relative risk"

# --- How "passing" an intersection is measured ------------------------------
# An intersection counts as passed if it lies within PASS_RADIUS_M of the route line.
# The route is first sampled every DENSIFY_SPACING_M so no part of it is skipped.
PASS_RADIUS_M = 25.0
DENSIFY_SPACING_M = 8.0
# --- The route risk score --------------------------------------------------------------------------------
# Every intersection the route passes contributes, not only the top-tier ones:
#
#     contribution = closeness x vulnerability x risk_index
#     route score  = sum of contributions over every intersection passed
#
# * risk_index is the model's predicted probability divided by the average for the same area, so 1.0 means
#   "an average intersection", 3.0 means "three times the average". The model has already weighed that
#   intersection's recent and long-run crash history, crashes at nearby intersections, speed limit, lanes, signals,
#   crossings and one-way streets.
# * closeness (0 to 1) is how squarely the route runs through the intersection: 1.0 on the route line, falling to
#   about 0.14 at the 25 m edge, so a street that merely runs alongside counts for less.
# * vulnerability is 1.0 for driving. For walking and cycling it rises with the fastest connecting speed limit and
#   with recent pedestrian (or cyclist) injury crashes there. These adjustments are judgement calls, not fitted to
#   data, and are kept small on purpose; the constants are below so they are easy to change or remove.
PROXIMITY_SIGMA_M = PASS_RADIUS_M / 2
HOT_INDEX = 3.0  # an intersection at least this many times riskier than the average one counts as a "hot spot"
MEANINGFUL_DIFFERENCE = 0.05  # routes whose scores differ by less than 5% are treated as equal
# An intersection the user reported (and asked to avoid) counts as passed when the route comes this close to its centre.
# A bit wider than PASS_RADIUS_M so a big or divided intersection is caught from any of its approaches.
AVOID_RADIUS_M = 40.0
MAX_AVOIDED = 50
VULNERABLE_HISTORY_COLUMN = {"WALK": "pedestrian_casualty_crashes_last_8w", "BICYCLE": "cyclist_casualty_crashes_last_8w"}
SPEED_BUMPS_MPH = ((35.0, 0.35), (26.0, 0.15))  # (at or above this speed, add this much), checked in order
HISTORY_BUMP_PER_CRASH = 0.25
HISTORY_BUMP_CAP_CRASHES = 3
INDEX_CAP_QUANTILE = 0.999  # one extreme outlier must not decide a whole route's score
TIER_ORDER = [TIER_HIGH, TIER_ELEVATED, "Moderate relative risk", "Lower relative risk"]

# For "is this route inside the area SafeCross covers?": the share of the route that has
# at least one known intersection within this distance. Generous on purpose: outside the dense city,
# highways and parkways can run more than a kilometre between mapped intersections, and that must
# not be mistaken for "outside the covered area".
COVERAGE_RADIUS_M = 1500.0

_EARTH_RADIUS_M = 6_371_008.8


class RoutingError(Exception):
    """An error whose message is safe and helpful to show directly to the user.
    Messages never contain the API key."""


# =============================================================================
# Geometry
# =============================================================================
def decode_polyline(encoded: str, precision: int = 5) -> np.ndarray:
    """Decode a Google encoded polyline into an (n, 2) array of [lat, lng]."""
    factor = 10.0**precision
    coordinates: list[tuple[float, float]] = []
    index = latitude = longitude = 0
    length = len(encoded)
    try:
        while index < length:
            for axis in (0, 1):
                shift = result = 0
                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else result >> 1
                if axis == 0:
                    latitude += delta
                else:
                    longitude += delta
            coordinates.append((latitude / factor, longitude / factor))
    except IndexError as error:
        raise ValueError("Malformed polyline") from error
    return np.array(coordinates, dtype=float).reshape(-1, 2)


def densify(xy: np.ndarray, spacing_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Resample a polyline (in metres) so consecutive points are at most `spacing_m` apart,
    keeping every original vertex. Returns the points and each point's distance along the route."""
    if len(xy) == 0:
        return xy.reshape(0, 2), np.zeros(0)
    if len(xy) == 1:
        return xy, np.zeros(1)
    segment_lengths = np.hypot(*np.diff(xy, axis=0).T)
    cumulative = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    total = float(cumulative[-1])
    if total == 0:
        return xy[:1], np.zeros(1)
    samples = np.linspace(0.0, total, max(int(math.ceil(total / spacing_m)), 1) + 1)
    along = np.unique(np.concatenate([cumulative, samples]))
    return np.column_stack([np.interp(along, cumulative, xy[:, 0]), np.interp(along, cumulative, xy[:, 1])]), along


# =============================================================================
# Intersection index
# =============================================================================
class IntersectionIndex:
    """Scored intersections plus a spatial index for fast "which are near this line" queries."""

    def __init__(self, frame: pd.DataFrame):
        missing = {"latitude", "longitude", "risk_tier"} - set(frame.columns)
        if missing:
            raise ValueError(f"Intersection data is missing columns: {sorted(missing)}")
        self.frame = frame.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
        if self.frame.empty:
            raise ValueError("No intersections with coordinates were found.")
        self.lat0 = float(self.frame["latitude"].median())
        self.lon0 = float(self.frame["longitude"].median())
        self.xy = self.project(self.frame["latitude"].to_numpy(float), self.frame["longitude"].to_numpy(float))
        self.tree = cKDTree(self.xy)
        self.bounds = (
            float(self.frame["latitude"].min()), float(self.frame["latitude"].max()),
            float(self.frame["longitude"].min()), float(self.frame["longitude"].max()),
        )

    @classmethod
    def from_scored(cls, scored: pd.DataFrame) -> "IntersectionIndex":
        """Build from the scored intersections (safecross_core.score_region + merge_intersection_info). Uses the
        most recent snapshot week if the data has several, and adds `risk_index` (see the score notes above)."""
        wanted = [
            "node_id", "latitude", "longitude", "risk_tier", "risk_percentile",
            "predicted_probability", "local_mean_probability", "intersection_label", "streets", "week_start",
            "region", "region_label", "validated",
            "max_connecting_speed_limit", "max_connecting_lanes", "is_traffic_signal", "is_crossing_tagged", "street_count",
            "sidewalk", "bike_lane", "lit", "node_control", "bridge_or_tunnel", "roundabout",
            "pedestrian_casualty_crashes_last_8w", "cyclist_casualty_crashes_last_8w",
        ]
        data = scored[[column for column in wanted if column in scored.columns]].copy()
        if "week_start" in data.columns:
            data = data.loc[data["week_start"] == data["week_start"].max()].copy()
        if "predicted_probability" in data.columns:
            groups = data["region"] if "region" in data.columns else pd.Series("all", index=data.index)
            probability = data["predicted_probability"].astype(float)
            # Relative to the intersection's own neighbourhood when score_region supplied it, else to its region.
            if "local_mean_probability" in data.columns:
                mean = data["local_mean_probability"].astype(float).replace(0, np.nan)
            else:
                mean = probability.groupby(groups).transform("mean").replace(0, np.nan)
            cap = (probability / mean).groupby(groups).transform(lambda s: s.quantile(INDEX_CAP_QUANTILE))
            data["risk_index"] = (probability / mean).clip(upper=cap).fillna(1.0)
        else:  # no probabilities: fall back to the tier so the score still means something
            data["risk_index"] = data["risk_tier"].map({TIER_HIGH: 4.0, TIER_ELEVATED: 2.0, "Moderate relative risk": 1.0}).fillna(0.5)
        return cls(data)

    @property
    def snapshot_week(self) -> str | None:
        if "week_start" not in self.frame.columns or self.frame.empty:
            return None
        return str(pd.Timestamp(self.frame["week_start"].iloc[0]).date())

    def project(self, latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
        """Local equirectangular projection (metres). Accurate to well under 1% across a city."""
        x = _EARTH_RADIUS_M * np.radians(np.asarray(longitude) - self.lon0) * math.cos(math.radians(self.lat0))
        y = _EARTH_RADIUS_M * np.radians(np.asarray(latitude) - self.lat0)
        return np.column_stack([x, y])

    def contains(self, latitude: float, longitude: float, margin_deg: float = 0.03) -> bool:
        south, north, west, east = self.bounds
        return (south - margin_deg <= latitude <= north + margin_deg) and (west - margin_deg <= longitude <= east + margin_deg)


# =============================================================================
# Routes and risk
# =============================================================================
@dataclass
class Route:
    label: str
    duration_s: int
    distance_m: float
    points: np.ndarray  # (n, 2) lat, lng
    google_labels: list[str] = field(default_factory=list)


@dataclass
class RouteRisk:
    n_intersections: int
    n_high: int
    n_elevated: int
    coverage: float
    passed: pd.DataFrame
    # How many of the passed intersections are in an area whose ranking has not been validated against
    # real crashes (currently Westchester County).
    n_unvalidated: int = 0
    # The route score (see the notes above) and what it is made of.
    score: float = 0.0
    score_per_mile: float = 0.0
    mean_index: float = 0.0  # average risk_index of the intersections passed (1.0 = an average intersection)
    n_hot: int = 0  # intersections passed with risk_index >= HOT_INDEX
    top_share: float = 0.0  # share of the score that comes from the three biggest contributors
    avoided_ids: list = field(default_factory=list)  # intersections the user reported that this route passes

    @property
    def n_high_or_elevated(self) -> int:
        return self.n_high + self.n_elevated


def analyze_route(
    route: Route,
    index: IntersectionIndex,
    radius_m: float = PASS_RADIUS_M,
    spacing_m: float = DENSIFY_SPACING_M,
    mode: str = "DRIVE",
) -> RouteRisk:
    """Find the intersections within `radius_m` of the route, count them by risk tier, and compute the route score
    from every one of them. `mode` is "DRIVE", "BICYCLE" or "WALK"."""
    xy = index.project(route.points[:, 0], route.points[:, 1])
    dense, along = densify(xy, spacing_m)

    candidate_rows = np.zeros(0, dtype=int)
    distance_along = np.zeros(0)
    distance_off = np.zeros(0)
    if len(dense):
        lo, hi = dense.min(axis=0) - radius_m, dense.max(axis=0) + radius_m
        in_box = (index.xy[:, 0] >= lo[0]) & (index.xy[:, 0] <= hi[0]) & (index.xy[:, 1] >= lo[1]) & (index.xy[:, 1] <= hi[1])
        box_rows = np.flatnonzero(in_box)
        if len(box_rows):
            distances, nearest = cKDTree(dense).query(index.xy[box_rows], distance_upper_bound=radius_m)
            hit = np.isfinite(distances)
            candidate_rows = box_rows[hit]
            distance_along = along[nearest[hit]]
            distance_off = distances[hit]

    passed = index.frame.iloc[candidate_rows].copy()
    passed["distance_along_route_m"] = distance_along
    passed["distance_from_route_m"] = distance_off
    passed = passed.sort_values("distance_along_route_m").reset_index(drop=True)

    coverage = 0.0
    if len(dense):
        sample = dense[:: max(1, int(50 / spacing_m))]
        near, _ = index.tree.query(sample, distance_upper_bound=COVERAGE_RADIUS_M)
        coverage = float(np.isfinite(near).mean())

    n_unvalidated = int((~passed["validated"].astype(bool)).sum()) if "validated" in passed.columns else 0

    passed = add_contributions(passed, mode)
    score = float(passed["contribution"].sum()) if len(passed) else 0.0
    miles = max(route.distance_m / 1609.344, 0.1)
    top3 = float(passed["contribution"].nlargest(3).sum()) if len(passed) else 0.0

    return RouteRisk(
        n_intersections=int(len(passed)),
        n_high=int((passed["risk_tier"] == TIER_HIGH).sum()),
        n_elevated=int((passed["risk_tier"] == TIER_ELEVATED).sum()),
        coverage=coverage,
        passed=passed,
        n_unvalidated=n_unvalidated,
        score=score,
        score_per_mile=score / miles,
        mean_index=float(passed["risk_index"].mean()) if len(passed) else 0.0,
        n_hot=int((passed["risk_index"] >= HOT_INDEX).sum()) if len(passed) else 0,
        top_share=(top3 / score) if score > 0 else 0.0,
    )


def mark_avoided(routes: list[Route], risks: list[RouteRisk], index: IntersectionIndex, avoid_ids) -> list[str]:
    """Fills `avoided_ids` on every RouteRisk with the reported intersections (node ids in `index`) the route passes
    within AVOID_RADIUS_M, and adds a boolean `avoided` column to `passed`. Returns the ids that were found in the index."""
    wanted = list(dict.fromkeys(str(n) for n in (avoid_ids or [])))[:MAX_AVOIDED]
    if not wanted or "node_id" not in index.frame.columns:
        for risk in risks:
            risk.passed = risk.passed.assign(avoided=False)
        return []
    ids = index.frame["node_id"].astype(str)
    rows = index.frame.index[ids.isin(wanted)].to_numpy()
    known = ids.iloc[rows].tolist()
    for route, risk in zip(routes, risks):
        risk.avoided_ids = []
        if len(rows):
            dense, _ = densify(index.project(route.points[:, 0], route.points[:, 1]), DENSIFY_SPACING_M)
            if len(dense):
                distances, _ = cKDTree(dense).query(index.xy[rows], distance_upper_bound=AVOID_RADIUS_M)
                risk.avoided_ids = [node for node, distance in zip(known, distances) if np.isfinite(distance)]
        node_ids = risk.passed["node_id"].astype(str) if "node_id" in risk.passed.columns else pd.Series(dtype=str)
        risk.passed = risk.passed.assign(avoided=node_ids.isin(risk.avoided_ids).to_numpy() if len(node_ids) else False)
    return known


def vulnerability_multiplier(passed: pd.DataFrame, mode: str) -> np.ndarray:
    """1.0 for driving. For walking and cycling: more weight where traffic is fast and where people on foot / bikes
    were recently hurt. Small, documented judgement calls (see the notes above), not fitted values."""
    multiplier = np.ones(len(passed))
    history_column = VULNERABLE_HISTORY_COLUMN.get(mode)
    if history_column is None:
        return multiplier
    if "max_connecting_speed_limit" in passed.columns:
        speed = pd.to_numeric(passed["max_connecting_speed_limit"], errors="coerce").to_numpy(float)
        for threshold, bump in SPEED_BUMPS_MPH:
            applies = np.nan_to_num(speed, nan=0.0) >= threshold
            already = multiplier > 1.0 + 1e-9
            multiplier = np.where(applies & ~already, multiplier + bump, multiplier)
    if history_column in passed.columns:
        crashes = pd.to_numeric(passed[history_column], errors="coerce").fillna(0).clip(0, HISTORY_BUMP_CAP_CRASHES).to_numpy(float)
        multiplier = multiplier + HISTORY_BUMP_PER_CRASH * crashes
    return multiplier


def add_contributions(passed: pd.DataFrame, mode: str = "DRIVE") -> pd.DataFrame:
    """Adds closeness, vulnerability and contribution columns to the intersections a route passes."""
    passed = passed.copy()
    if passed.empty:
        for column in ("closeness", "vulnerability", "contribution"):
            passed[column] = pd.Series(dtype=float)
        return passed
    index = pd.to_numeric(passed["risk_index"], errors="coerce").fillna(1.0).to_numpy(float)
    off = pd.to_numeric(passed["distance_from_route_m"], errors="coerce").fillna(PASS_RADIUS_M).to_numpy(float)
    passed["closeness"] = np.exp(-0.5 * (off / PROXIMITY_SIGMA_M) ** 2)
    passed["vulnerability"] = vulnerability_multiplier(passed, mode)
    passed["contribution"] = passed["closeness"] * passed["vulnerability"] * index
    return passed


@dataclass
class Comparison:
    fastest_idx: int
    safest_idx: int
    recommended_idx: int
    counts_differ: bool
    badges: dict[int, list[str]]
    headline: str


def format_duration(seconds: float) -> str:
    minutes = max(int(round(seconds / 60)), 1)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min"


def format_distance(meters: float) -> str:
    miles = meters / 1609.344
    return f"{miles:.1f} mi" if miles >= 0.1 else f"{int(round(meters * 3.28084))} ft"


def format_minutes_delta(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    return f"{minutes:+d} min"


def compare_routes(routes: list[Route], risks: list[RouteRisk]) -> Comparison:
    """Pick the fastest route and the one with the lowest risk SCORE (ties go to the faster route) and describe the
    trade-off in one sentence. Scores that differ by less than MEANINGFUL_DIFFERENCE are treated as equal.
    Intersections the user reported come first: if some options pass fewer of them, only those can be recommended."""
    reported = [len(risk.avoided_ids) for risk in risks]
    if min(reported) < max(reported):
        keep = [i for i in range(len(routes)) if reported[i] == min(reported)]
        inner = compare_routes([routes[i] for i in keep], [risks[i] for i in keep])
        pick = keep[inner.recommended_idx]
        fastest = min(range(len(routes)), key=lambda i: routes[i].duration_s)
        badges: dict[int, list[str]] = {i: [] for i in range(len(routes))}
        badges[fastest].append("Fastest")
        for position, badge_list in inner.badges.items():
            badges[keep[position]] += [b for b in badge_list if b != "Fastest" and b not in badges[keep[position]]]
        what = "the intersection you reported" if max(reported) == 1 else "the intersections you reported"
        if min(reported) == 0:
            for i in keep:
                badges[i].insert(0, "Avoids your reports")
            verb = f"avoids {what}"
        else:
            verb = f"passes the fewest of {what}"
        extra = routes[pick].duration_s - routes[fastest].duration_s
        if pick == fastest:
            time_part = "and is also the fastest option"
        elif round(extra / 60) >= 1:
            time_part = f"and takes **{format_duration(extra)} longer** than the fastest route ({routes[fastest].label})"
        else:
            time_part = "and takes about the same time as the fastest route"
        headline = f"**{routes[pick].label}** {verb} {time_part}. Its risk score is {risks[pick].score:.1f}."
        safest = keep[inner.safest_idx]
        return Comparison(
            fastest_idx=fastest, safest_idx=safest, recommended_idx=pick, counts_differ=True, badges=badges, headline=headline,
        )

    fastest = min(range(len(routes)), key=lambda i: routes[i].duration_s)
    safest = min(range(len(routes)), key=lambda i: (round(risks[i].score, 6), routes[i].duration_s))
    top, low = max(r.score for r in risks), min(r.score for r in risks)
    counts_differ = top > 0 and (top - low) / top >= MEANINGFUL_DIFFERENCE

    badges: dict[int, list[str]] = {i: [] for i in range(len(routes))}
    badges[fastest].append("Fastest")
    if counts_differ:
        badges[safest].append("Lowest risk score")

    if len(routes) == 1:
        headline = f"Only one route option was available for this trip. Its risk score is {risks[0].score:.1f}."
    elif not counts_differ:
        headline = (
            f"All {len(routes)} routes have a similar risk score ({low:.1f} to {top:.1f}), "
            "so travel time is the main difference."
        )
    elif safest == fastest:
        headline = (
            f"**{routes[fastest].label}** is both the fastest option and has the lowest risk score ({risks[fastest].score:.1f})."
        )
    else:
        percent = (risks[fastest].score - risks[safest].score) / risks[fastest].score * 100 if risks[fastest].score > 0 else 0
        extra = routes[safest].duration_s - routes[fastest].duration_s
        time_part = (
            f"takes **{format_duration(extra)} longer**" if round(extra / 60) >= 1 else "takes about the same time"
        )
        headline = (
            f"**{routes[safest].label}** has a **{percent:.0f}% lower risk score** "
            f"than the fastest route ({routes[fastest].label}) and {time_part}."
        )

    return Comparison(
        fastest_idx=fastest, safest_idx=safest, recommended_idx=safest if counts_differ else fastest,
        counts_differ=counts_differ, badges=badges, headline=headline,
    )


# =============================================================================
# Places, request building, API call
# =============================================================================
_COORDINATE_PATTERN = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_NYC_PATTERN = re.compile(r"\b(ny|n\.y\.|new york|nyc|manhattan|brooklyn|queens|bronx|staten island)\b", re.IGNORECASE)


def parse_coordinates(text: str) -> tuple[float, float] | None:
    match = _COORDINATE_PATTERN.match(text or "")
    if not match:
        return None
    latitude, longitude = float(match.group(1)), float(match.group(2))
    if abs(latitude) > 90 or abs(longitude) > 180:
        return None
    return latitude, longitude


def with_city_bias(text: str) -> str:
    """SafeCross only covers New York City, so an address with no place name is assumed to be there."""
    text = text.strip()
    if parse_coordinates(text) or _NYC_PATTERN.search(text):
        return text
    return f"{text}, New York, NY"


def waypoint_for(text: str) -> dict:
    coordinates = parse_coordinates(text)
    if coordinates:
        return {"location": {"latLng": {"latitude": coordinates[0], "longitude": coordinates[1]}}}
    return {"address": with_city_bias(text)}


def build_request_body(origin: str, destination: str, travel_mode: str, alternatives: bool = True) -> dict:
    body = {
        "origin": waypoint_for(origin),
        "destination": waypoint_for(destination),
        "travelMode": travel_mode,
        "computeAlternativeRoutes": alternatives,
        # HIGH_QUALITY keeps corners and turns. The simplified OVERVIEW line can cut corners by
        # tens of metres, which would make intersection matching unreliable.
        "polylineQuality": "HIGH_QUALITY",
        "languageCode": "en-US",
        "units": "IMPERIAL",
        "regionCode": "US",
    }
    if travel_mode == "DRIVE":  # routingPreference only applies to driving / two-wheeler
        body["routingPreference"] = "TRAFFIC_AWARE"
    return body


def _error_text(response) -> str:
    try:
        return str(response.json().get("error", {}).get("message", ""))
    except Exception:
        return ""


def _raise_for_response(response) -> None:
    status = response.status_code
    if status == 200:
        return
    detail = _error_text(response)
    if status in (401, 403):
        raise RoutingError(
            "Google rejected the Routes API key. Check that the Routes API is enabled for the project, "
            "billing is on, and the key's restrictions allow the Routes API."
        )
    if status == 429:
        raise RoutingError("Google's usage limit was reached. Please try again in a minute.")
    if status in (400, 404):
        raise RoutingError(
            "Google couldn't find a route between those places. Check both addresses (or use "
            f"'latitude, longitude').{' Details: ' + detail if detail else ''}"
        )
    if status >= 500:
        raise RoutingError("Google Maps is temporarily unavailable. Please try again shortly.")
    raise RoutingError(f"Google returned an unexpected error (HTTP {status}).")


def _parse_duration(value) -> int:
    return int(round(float(str(value).rstrip("s"))))


def parse_routes(data: dict) -> list[Route]:
    routes: list[Route] = []
    for item in data.get("routes") or []:
        encoded = (item.get("polyline") or {}).get("encodedPolyline")
        if not encoded or "duration" not in item:
            continue
        try:
            points = decode_polyline(encoded)
        except ValueError:
            continue
        if len(points) < 2:
            continue
        routes.append(
            Route(
                label="",
                duration_s=_parse_duration(item["duration"]),
                distance_m=float(item.get("distanceMeters", 0)),
                points=points,
                google_labels=list(item.get("routeLabels") or []),
            )
        )
    routes.sort(key=lambda route: route.duration_s)
    routes = routes[:MAX_ROUTES]
    for position, route in enumerate(routes):
        route.label = f"Route {chr(ord('A') + position)}"
    return routes


def fetch_routes(
    api_key: str,
    origin: str,
    destination: str,
    travel_mode: str = "DRIVE",
    *,
    http_post: Callable = requests.post,
    timeout: float = REQUEST_TIMEOUT_S,
) -> tuple[list[Route], list[str]]:
    """Ask Google for route options. Returns (routes, notices). Raises RoutingError with a
    user-safe message on any failure. The API key is sent only in a header, never in a URL."""
    if not origin.strip() or not destination.strip():
        raise RoutingError("Enter both a starting point and a destination.")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ROUTES_FIELD_MASK,
    }

    def post(alternatives: bool):
        try:
            return http_post(
                ROUTES_ENDPOINT,
                json=build_request_body(origin, destination, travel_mode, alternatives),
                headers=headers,
                timeout=timeout,
            )
        except requests.Timeout as error:
            raise RoutingError("Google Maps took too long to respond. Please try again.") from error
        except requests.RequestException as error:
            raise RoutingError("Couldn't reach Google Maps. Check your internet connection and try again.") from error

    notices: list[str] = []
    response = post(alternatives=True)
    if response.status_code == 400 and "alternative" in _error_text(response).lower():
        notices.append("Google doesn't offer alternative routes for this travel mode, so only one route is shown.")
        response = post(alternatives=False)
    _raise_for_response(response)

    try:
        data = response.json()
    except ValueError as error:
        raise RoutingError("Google returned a response that couldn't be read. Please try again.") from error

    routes = parse_routes(data)
    if not routes:
        raise RoutingError("No route was found between those places for this travel mode.")
    if len(routes) == 1 and not notices:
        notices.append("Google returned only one route option for this trip.")
    return routes, notices


def google_maps_directions_url(
    origin: str, destination: str, travel_mode: str, waypoints: list[tuple[float, float]] | None = None
) -> str:
    """A plain Google Maps link (no API key) that opens the trip in the Google Maps app/site. `waypoints`
    (lat, lng) pin the link to one particular route (see route_waypoints)."""
    params = {
        "api": 1,
        "origin": with_city_bias(origin),
        "destination": with_city_bias(destination),
        "travelmode": MAPS_URL_MODES.get(travel_mode, "driving"),
    }
    if waypoints:
        params["waypoints"] = "|".join(f"{lat:.6f},{lng:.6f}" for lat, lng in waypoints)
    return f"https://www.google.com/maps/dir/?{urllib.parse.urlencode(params)}"


# Google Maps URLs accept at most 3 waypoints on mobile browsers (9 elsewhere), and the link is meant for phones.
WAYPOINT_COUNT = 3
WAYPOINT_SPACING_M = 20.0
WAYPOINT_MIN_DEVIATION_M = 40.0  # a point this far from every other option is where this route "goes its own way"
WAYPOINT_CLEARANCE_M = 30.0  # keep waypoints off intersections, where Google could snap them onto the cross street
WAYPOINT_MIN_ROUTE_M = 400.0


def route_waypoints(routes: list[Route], position: int, index: IntersectionIndex, count: int = WAYPOINT_COUNT) -> list[tuple[float, float]]:
    """Up to `count` points on route `position` that make Google Maps follow that route rather than its own pick.

    The middle 80% of the route is split into `count` equal sections. In each, the waypoint is the point farthest
    from every other route option, if it strays at least WAYPOINT_MIN_DEVIATION_M from them, else the section's
    midpoint. Points within WAYPOINT_CLEARANCE_M of an intersection are avoided when the section has others."""
    route = routes[position]
    if len(route.points) < 2:
        return []
    xy = index.project(route.points[:, 0], route.points[:, 1])
    dense, along = densify(xy, WAYPOINT_SPACING_M)
    total = float(along[-1])
    if total < WAYPOINT_MIN_ROUTE_M:
        return []
    vertex_along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    latitude = np.interp(along, vertex_along, route.points[:, 0])
    longitude = np.interp(along, vertex_along, route.points[:, 1])

    others = [densify(index.project(other.points[:, 0], other.points[:, 1]), WAYPOINT_SPACING_M)[0]
              for i, other in enumerate(routes) if i != position and len(other.points) >= 2]
    deviation = cKDTree(np.vstack(others)).query(dense)[0] if others else np.zeros(len(dense))
    clearance = index.tree.query(dense)[0]

    waypoints = []
    edges = np.linspace(0.1 * total, 0.9 * total, count + 1)
    for low, high in zip(edges[:-1], edges[1:]):
        section = (along >= low) & (along < high)
        clear = section & (clearance >= WAYPOINT_CLEARANCE_M)
        candidates = np.flatnonzero(clear if clear.any() else section)
        if not len(candidates):
            continue
        if deviation[candidates].max() >= WAYPOINT_MIN_DEVIATION_M:
            pick = candidates[np.argmax(deviation[candidates])]
        else:
            pick = candidates[np.argmin(np.abs(along[candidates] - (low + high) / 2))]
        waypoints.append((float(latitude[pick]), float(longitude[pick])))
    return waypoints


# =============================================================================
# Payload for the Google Map
# =============================================================================
def build_map_payload(routes: list[Route], risks: list[RouteRisk], colors: list[str]) -> dict:
    """Everything the in-browser Google Map needs: route lines, and one dot per distinct intersection the routes
    pass (every tier), with the list of routes that pass it. The browser filters dots by tier."""
    route_entries = [
        {
            "label": route.label,
            "color": colors[i % len(colors)],
            "points": [[round(float(lat), 5), round(float(lng), 5)] for lat, lng in route.points],
            "minutes": int(max(round(route.duration_s / 60), 1)),
            "high": risk.n_high,
            "elevated": risk.n_elevated,
            "score": round(risk.score, 2),
        }
        for i, (route, risk) in enumerate(zip(routes, risks))
    ]

    tier_code = {name: code for code, name in enumerate(TIER_ORDER)}
    dots: dict[str, dict] = {}
    for route, risk in zip(routes, risks):
        for row in risk.passed.itertuples(index=False):
            key = str(getattr(row, "node_id", f"{row.latitude:.6f},{row.longitude:.6f}"))
            percentile = getattr(row, "risk_percentile", np.nan)
            entry = dots.setdefault(
                key,
                {
                    "id": key,
                    "lat": round(float(row.latitude), 5),
                    "lng": round(float(row.longitude), 5),
                    "tier": tier_code.get(row.risk_tier, 3),
                    "label": str(getattr(row, "intersection_label", key)),
                    "pct": int(round(float(percentile))) if pd.notna(percentile) else None,
                    "unvalidated": not bool(getattr(row, "validated", True)),
                    "routes": [],
                },
            )
            entry["routes"].append(route.label)

    all_points = np.vstack([route.points for route in routes])
    return {
        "routes": route_entries,
        "dots": list(dots.values()),
        "hasUnvalidated": any(dot["unvalidated"] for dot in dots.values()),
        "start": [round(float(routes[0].points[0, 0]), 5), round(float(routes[0].points[0, 1]), 5)],
        "end": [round(float(routes[0].points[-1, 0]), 5), round(float(routes[0].points[-1, 1]), 5)],
        "center": [round(float(all_points[:, 0].mean()), 5), round(float(all_points[:, 1].mean()), 5)],
    }
